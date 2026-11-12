"""Parser for IBKR Activity Statement CSV exports (Statements -> Activity -> Annual/Custom -> CSV).

Every CSV line is `Section,RowType,field1,field2,...`. A `Header` row defines the columns for
the following `Data`/`Total`/`SubTotal` rows of that section; headers can change mid-section
(e.g. Trades: Stocks vs Forex), so the latest header is always used.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .model import CashLine, ForexBalance, NavRow, Position, RURow, Statement
from .parse_common import CFD_CLASSES, CRYPTO_CLASSES, NON_FIFO_CODES, OPTION_CLASSES, codes, convert_groups, finalize_positions, parse_period, to_num

CASH_MAP = {
    "Interest": "interest", "Fees": "fees", "Withholding Tax": "withholding",
    "Dividends": "dividends", "Payment In Lieu Of Dividends": "dividends",
    "Deposits & Withdrawals": "deposits", "Transaction Fees": "transaction_fee_lines",
}


def parse_csv(path_or_text: str | Path, name: str | None = None) -> Statement:
    if isinstance(path_or_text, Path) or (isinstance(path_or_text, str) and "\n" not in path_or_text):
        p = Path(path_or_text)
        text = p.read_text(encoding="utf-8-sig")
        name = name or p.name
    else:
        text = str(path_or_text).lstrip("﻿")
    st = Statement(source_files=[name or "statement.csv"])

    headers: dict[str, list[str]] = {}
    rows: dict[str, list[tuple[str, dict]]] = {}
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 2:
            continue
        sec, kind, fields = rec[0].strip(), rec[1].strip(), rec[2:]
        if kind == "Header":
            headers[sec] = fields
            rows.setdefault(sec, []).append(("Header", dict(enumerate(fields))))
            continue
        h = headers.get(sec, [])
        d = {h[i] if i < len(h) else f"_{i}": v for i, v in enumerate(fields)}
        rows.setdefault(sec, []).append((kind, d))

    def data(sec):
        return [d for k, d in rows.get(sec, []) if k == "Data"]

    # ---- statement / account
    for d in data("Statement"):
        fn, fv = d.get("Field Name", ""), d.get("Field Value", "")
        if fn == "Title":
            st.title = fv
        elif fn == "Period":
            st.period_start, st.period_end = parse_period(fv)
    for d in data("Account Information"):
        fn, fv = d.get("Field Name", ""), d.get("Field Value", "")
        if fn == "Name":
            st.name = fv
        elif fn == "Account":
            st.account = fv
        elif fn == "Base Currency":
            st.base_currency = fv
        elif fn == "Customer Type":
            st.customer_type = fv
    base = st.base_currency

    # ---- NAV
    for d in data("Net Asset Value"):
        lab = (d.get("Asset Class") or "").strip()
        if not lab or "Current Total" not in d:
            continue
        st.nav[lab] = NavRow(lab, to_num(d.get("Prior Total")), to_num(d.get("Current Long")),
                             to_num(d.get("Current Short")), to_num(d.get("Current Total")))
    for d in data("Change in NAV"):
        if d.get("Field Name"):
            st.change_in_nav[d["Field Name"].strip()] = to_num(d.get("Field Value"))

    # ---- Realized & Unrealized
    for d in data("Realized & Unrealized Performance Summary"):
        cls, sym = (d.get("Asset Category") or "").strip(), (d.get("Symbol") or "").strip()
        if not sym or cls.startswith("Total") or sym.startswith("Total"):
            continue
        st.ru.append(RURow(
            cls, sym,
            to_num(d.get("Realized S/T Profit")), to_num(d.get("Realized S/T Loss")),
            to_num(d.get("Realized L/T Profit")), to_num(d.get("Realized L/T Loss")),
            to_num(d.get("Unrealized S/T Profit")) + to_num(d.get("Unrealized L/T Profit")),
            to_num(d.get("Unrealized S/T Loss")) + to_num(d.get("Unrealized L/T Loss"))))

    # ---- Open positions (Summary rows + Total rows in base currency)
    groups: dict[tuple, dict] = {}
    for kind, d in rows.get("Open Positions", []):
        if kind == "Data" and d.get("DataDiscriminator", "Summary") == "Summary":
            cls, ccy = d.get("Asset Category", ""), d.get("Currency", "")
            g = groups.setdefault((cls, ccy), {"cls": cls, "ccy": ccy, "rows": [], "eur": None})
            g["rows"].append(Position(cls, ccy, d.get("Symbol", ""), to_num(d.get("Quantity")),
                                      to_num(d.get("Mult")) or 1, to_num(d.get("Cost Price")),
                                      to_num(d.get("Cost Basis")), to_num(d.get("Close Price")),
                                      to_num(d.get("Value")), to_num(d.get("Unrealized P/L"))))
        elif kind == "Total" and d.get("Currency") == base:
            cls = d.get("Asset Category", "")
            # the EUR total row follows the native-currency total rows of the same class
            for (c, ccy), g in groups.items():
                if c == cls and ccy != base and g["eur"] is None:
                    if len([1 for (c2, k2) in groups if c2 == cls and k2 != base]) == 1:
                        g["eur"] = (to_num(d.get("Cost Basis")), to_num(d.get("Value")),
                                    to_num(d.get("Unrealized P/L")))
    finalize_positions(list(groups.values()), base, st)
    multi = [k for k in groups if groups[k]["eur"] is None and k[1] != base]
    if multi:
        st.warnings.append("Open Positions: several foreign currencies in one asset class; "
                           "EUR values approximated from Forex Balances is not implemented — check positions sheet")

    for d in data("Forex Balances"):
        ccy = d.get("Description") or d.get("Currency")
        if ccy and d.get("Asset Category", "Forex") == "Forex" and ccy != "Total":
            st.forex_balances.append(ForexBalance(ccy, to_num(d.get("Quantity")),
                                                  to_num(d.get(f"Cost Basis in {base}")),
                                                  to_num(d.get(f"Value in {base}")),
                                                  to_num(d.get(f"Unrealized P/L in {base}"))))

    # ---- Trades: commissions in base currency from Total rows (Currency == base)
    comm: dict[str, float] = {}
    for kind, d in rows.get("Trades", []):
        cls = d.get("Asset Category", "")
        if kind == "Total" and d.get("Currency") == base and cls != "Forex":
            comm[cls] = comm.get(cls, 0.0) + to_num(d.get("Comm/Fee"))
        elif kind == "Data" and cls == "Forex" and d.get("DataDiscriminator", "Order") in ("Order", "Trade", ""):
            comm[cls] = comm.get(cls, 0.0) + to_num(d.get(f"Comm in {base}"))
    if comm:
        st.commissions_by_class = comm
        st.commissions_eur = sum(comm.values())
    # stock legs: base-currency rows exact; others converted with the class Total-in-base / Total proceeds ratio
    tot_ccy, tot_base = {}, {}
    for kind, d in rows.get("Trades", []):
        if kind == "Total" and d.get("Asset Category") == "Stocks":
            (tot_base if d.get("Currency") == base else tot_ccy)[d.get("Currency")] = to_num(d.get("Comm/Fee"))
    ratio = None
    if len(tot_ccy) == 1 and list(tot_base.values()):
        c0, v0 = next(iter(tot_ccy.items()))
        eur_tot = sum(tot_base.values()) - sum(to_num(d.get("Proceeds")) for k, d in rows.get("Trades", [])
                                                   if k == "Total" and d.get("Asset Category") == "Stocks"
                                                   and d.get("Currency") == base and False)
        ratio = {c0: (list(tot_base.values())[-1] / v0) if v0 else None}
    for kind, d in rows.get("Trades", []):
        if kind != "Data" or d.get("Asset Category") != "Stocks" or d.get("DataDiscriminator", "Order") not in ("Order", "Trade"):
            continue
        q, ccy = to_num(d.get("Quantity")), d.get("Currency", "")
        # IBKR Comm/Fee is negative: buy cost = |proceeds + comm| (more), sale price = proceeds + comm (less)
        comm = abs(to_num(d.get("Comm/Fee")))
        amt = abs(to_num(d.get("Proceeds")) + to_num(d.get("Comm/Fee")))
        dt = d.get("Date/Time") or ""
        st.trade_rows.append({"date": dt[:10], "time": dt[12:20].strip(), "symbol": d.get("Symbol", ""), "qty": q,
                              "comm": comm, "ccy": ccy})
        if ccy == base:
            st.stock_legs.append({"date": dt[:10], "time": dt[12:20].strip(), "symbol": d.get("Symbol", ""), "qty": q,
                                  "ccy": ccy, "eur": amt, "comm_eur": comm, "exact": True})
        elif ratio and ratio.get(ccy):
            st.stock_legs.append({"date": dt[:10], "time": dt[12:20].strip(), "symbol": d.get("Symbol", ""), "qty": q,
                                  "ccy": ccy, "eur": amt * abs(ratio[ccy]), "comm_eur": comm * abs(ratio[ccy]),
                                  "cash": amt, "comm_ccy": comm, "exact": False})

    st.cfd_trades = _cfd_trades(rows.get("Trades", []), base)
    cratio = _class_ratio(rows.get("Trades", []), CRYPTO_CLASSES, base)
    for kind, d in rows.get("Trades", []):
        cls = d.get("Asset Category", "")
        if kind != "Data" or cls not in CRYPTO_CLASSES or d.get("DataDiscriminator", "Order") not in ("Order", "Trade", ""):
            continue
        q, ccy, dt = to_num(d.get("Quantity")), d.get("Currency", ""), d.get("Date/Time") or ""
        comm, cash = abs(to_num(d.get("Comm/Fee"))), abs(to_num(d.get("Proceeds")) + to_num(d.get("Comm/Fee")))
        rate = 1.0 if ccy == base else (abs(cratio[(cls, ccy)]) if (cls, ccy) in cratio else None)
        if rate is None:
            st.warnings.append(f"Kryptokauppa {d.get('Symbol', '')} ({ccy}) ilman EUR-muunnosta — ohitettu.")
            continue
        st.crypto_legs.append({"date": dt[:10], "time": dt[12:20].strip(), "symbol": d.get("Symbol", ""), "qty": q,
                               "ccy": ccy, "eur": cash * rate, "comm_eur": comm * rate, "cash": cash, "comm_ccy": comm,
                               "exact": ccy == base})
    info = {(d.get("Symbol") or "").strip(): d for d in data("Financial Instrument Information")
            if (d.get("Asset Category") or "").strip() in OPTION_CLASSES}
    st.option_trades = _option_trades(rows.get("Trades", []), base, info)
    for kind, d in rows.get("Trades", []):
        if kind != "Data" or d.get("Asset Category") != "Stocks":
            continue
        cs = codes(d.get("Code"))
        if cs & {"Ex", "A"}:
            st.exercise_rows.append({"date": (d.get("Date/Time") or "")[:10], "symbol": d.get("Symbol", ""),
                                     "qty": to_num(d.get("Quantity")), "basis": to_num(d.get("Basis")),
                                     "cash": to_num(d.get("Proceeds")), "ccy": d.get("Currency", ""),
                                     "code": d.get("Code", "")})
        if cs & NON_FIFO_CODES and not any("FIFO" in w for w in st.warnings):
            st.warnings.append("IBKR on käyttänyt joissakin kaupoissa muuta erätäsmäytystä kuin FIFO:a (koodi "
                               + ", ".join(sorted(cs & NON_FIFO_CODES)) + "). Verohallinto edellyttää FIFO-järjestystä; "
                               "tämä laskelma käyttää FIFO:a, joten tulos voi poiketa IBKR:n luvuista.")


    # ---- Corporate Actions (shares): no Symbol column — the symbol starts the description ('AAA(US…) Split 4 for 1 …')
    for d in data("Corporate Actions"):
        cls, desc = (d.get("Asset Category") or "").strip(), (d.get("Description") or "").strip()
        if cls != "Stocks" or not desc or desc.startswith("Total"):
            continue
        ccy, proceeds = d.get("Currency", ""), to_num(d.get("Proceeds"))
        rate = 1.0 if ccy == base else (abs(ratio[ccy]) if ratio and ratio.get(ccy) else None)
        st.corporate_actions.append({"date": (d.get("Date/Time") or d.get("Report Date") or "")[:10],
                                     "symbol": desc.split("(")[0].strip(), "description": desc,
                                     "qty": to_num(d.get("Quantity")), "ccy": ccy,
                                     "proceeds_eur": proceeds * rate if rate is not None else None})

    # ---- Cash sections
    for sec, attr in CASH_MAP.items():
        lines: list[CashLine] = []
        gt, gte, total_eur = {}, {}, None
        for d in data(sec):
            ccy = (d.get("Currency") or "").strip()
            if (d.get("Subtitle") or "").startswith("Total"):
                ccy = d["Subtitle"].strip()
            amt = to_num(d.get("Amount"))
            if ccy.startswith("Total"):
                # 'Total Interest in EUR' etc. = section total in base currency
                if ccy.endswith(f"in {base}") and ccy != f"Total in {base}":
                    total_eur = (total_eur or 0.0) + amt
                continue
            if (d.get("Asset Category") or "").startswith("Total"):
                continue
            date = d.get("Date") or d.get("Settle Date") or d.get("Date/Time", "")
            desc = d.get("Description") or d.get("Symbol", "")
            lines.append(CashLine(date[:10], ccy, desc, amt))
        for ln in lines:
            gt[ln.currency] = gt.get(ln.currency, 0.0) + ln.amount
        # IBKR CSV prints 'Total' rows with Currency='Total' and 'Total in EUR' after each ccy block
        cur = None
        for kind, d in rows.get(sec, []):
            if kind != "Data":
                continue
            c = (d.get("Currency") or "").strip()
            if (d.get("Subtitle") or "").startswith("Total"):
                c = d["Subtitle"].strip()
            if not c.startswith("Total"):
                cur = c
            elif c == f"Total in {base}" and cur:
                gte[cur] = to_num(d.get("Amount"))
        convert_groups(lines, gt, gte, base, st.warnings, sec)
        if not lines:
            continue
        if attr == "dividends" and st.dividends:
            st.dividends += lines
        else:
            setattr(st, attr, lines)
        tot = total_eur if total_eur is not None else sum(x.amount_eur for x in lines)
        if attr == "transaction_fee_lines":
            st.transaction_fees_eur = tot
        elif attr == "dividends":
            st.dividends_total_eur = sum(x.amount_eur for x in st.dividends)
        else:
            setattr(st, f"{attr}_total_eur", tot)

    # ---- ETF flags (EVL 8 a § applies to shares, not ETFs)
    for d in data("Financial Instrument Information"):
        if (d.get("Type") or "").upper() in ("ETF", "ETN", "ETC", "FUND"):
            st.etf_symbols.add(d.get("Symbol", ""))
    for d in data("Financial Instrument Information"):
        ex = (d.get("Listing Exch") or "").strip()
        if ex and d.get("Symbol"):
            st.listing_exch[d["Symbol"].strip()] = ex
    return st


def _cfd_trades(trades: list[tuple[str, dict]], base: str) -> list[dict]:
    """Realized P/L of each closing CFD trade, converted to base currency.

    Non-base rows use the class's commission ratio (Total row in base / Total row in the trade currency); commissions
    always have the same sign, so the ratio is stable even when the net P/L is close to zero. When a class has several
    foreign currencies the ratio is unknown and `eur` stays None (the personal engine then falls back to IBKR R&U)."""
    out, native, conv = [], {}, {}
    for kind, d in trades:
        cls = d.get("Asset Category", "")
        if cls not in CFD_CLASSES:
            continue
        if kind == "Total":
            ccy = d.get("Currency", "")
            if ccy == base:
                conv.setdefault(cls, []).append(to_num(d.get("Comm/Fee")))
            else:
                native.setdefault(cls, {})[ccy] = to_num(d.get("Comm/Fee"))
        elif kind == "Data" and d.get("DataDiscriminator", "Order") in ("Order", "Trade", ""):
            pl = to_num(d.get("Realized P/L"))
            if pl:
                out.append({"date": (d.get("Date/Time") or "")[:10], "symbol": d.get("Symbol", ""), "cls": cls,
                            "ccy": d.get("Currency", ""), "pl": pl, "eur": None})
    ratio: dict[tuple[str, str], float] = {}
    for cls, by_ccy in native.items():
        base_tot = conv.get(cls, [])
        if len(by_ccy) == 1 and base_tot:
            ccy, comm = next(iter(by_ccy.items()))
            # with native base-currency CFDs IBKR prints that block's Total first, then the overall base Total
            eur_comm = base_tot[-1] - (base_tot[0] if len(base_tot) > 1 else 0.0)
            if comm:
                ratio[(cls, ccy)] = eur_comm / comm
    for x in out:
        if x["ccy"] == base:
            x["eur"] = x["pl"]
        elif (x["cls"], x["ccy"]) in ratio:
            x["eur"] = x["pl"] * ratio[(x["cls"], x["ccy"])]
    return out


def _class_ratio(trades: list[tuple[str, dict]], classes: set[str], base: str) -> dict[tuple[str, str], float]:
    """Base-currency conversion per (class, currency) from the commission Total rows (see _cfd_trades)."""
    native, conv = {}, {}
    for kind, d in trades:
        cls = d.get("Asset Category", "")
        if cls in classes and kind == "Total":
            ccy = d.get("Currency", "")
            if ccy == base:
                conv.setdefault(cls, []).append(to_num(d.get("Comm/Fee")))
            else:
                native.setdefault(cls, {})[ccy] = to_num(d.get("Comm/Fee"))
    out = {}
    for cls, by_ccy in native.items():
        base_tot = conv.get(cls, [])
        if len(by_ccy) == 1 and base_tot:
            ccy, comm = next(iter(by_ccy.items()))
            eur_comm = base_tot[-1] - (base_tot[0] if len(base_tot) > 1 else 0.0)
            if comm:
                out[(cls, ccy)] = eur_comm / comm
    return out


def _option_meta(sym: str, info: dict) -> tuple[str, str, float]:
    """(underlying, 'C'/'P', multiplier) from Financial Instrument Information, else from 'AAA 17JUN26 100 C'."""
    d = info.get(sym) or {}
    toks = sym.split()
    und = (d.get("Underlying") or (toks[0] if toks else "")).strip()
    right = (d.get("Type") or (toks[-1] if toks else "")).strip().upper()[:1]
    mult = to_num(d.get("Multiplier")) or 100.0
    return und, right if right in ("C", "P") else "", mult


def _option_trades(trades: list[tuple[str, dict]], base: str, info: dict) -> list[dict]:
    ratio = _class_ratio(trades, OPTION_CLASSES, base)
    out = []
    for kind, d in trades:
        cls = d.get("Asset Category", "")
        if kind != "Data" or cls not in OPTION_CLASSES or d.get("DataDiscriminator", "Order") not in ("Order", "Trade", ""):
            continue
        sym, q, ccy = (d.get("Symbol") or "").strip(), to_num(d.get("Quantity")), d.get("Currency", "")
        und, right, mult = _option_meta(sym, info)
        cash = abs(to_num(d.get("Proceeds")) + to_num(d.get("Comm/Fee")))   # paid incl. / received net of commission
        rate = 1.0 if ccy == base else ratio.get((cls, ccy))
        out.append({"date": (d.get("Date/Time") or "")[:10], "symbol": sym, "underlying": und, "right": right,
                    "mult": mult, "qty": q, "ccy": ccy, "code": d.get("Code", ""),
                    "eur": cash * abs(rate) if rate is not None else None})
    return out
