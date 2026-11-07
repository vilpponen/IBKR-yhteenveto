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
from .parse_common import convert_groups, finalize_positions, parse_period, to_num

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
        amt = abs(to_num(d.get("Proceeds")) + (to_num(d.get("Comm/Fee")) if q < 0 else -to_num(d.get("Comm/Fee"))))
        if ccy == base:
            st.stock_legs.append({"date": (d.get("Date/Time") or "")[:10], "symbol": d.get("Symbol", ""), "qty": q,
                                  "ccy": ccy, "eur": amt, "exact": True})
        elif ratio and ratio.get(ccy):
            st.stock_legs.append({"date": (d.get("Date/Time") or "")[:10], "symbol": d.get("Symbol", ""), "qty": q,
                                  "ccy": ccy, "eur": amt * abs(ratio[ccy]), "exact": False})

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
    return st
