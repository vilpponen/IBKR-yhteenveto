"""Books engine: IBKR statement -> Finnish bookkeeping (KPL) result, balance sheet and EVL bridge.

Method (no plugs):
  1. Economic result E = NAV end - NAV start - net deposits.                (ties to IBKR by definition)
  2. Explicit non-trading items N = dividends + WHT + interest + accrual changes + fees + FTT.
  3. Trading result T = E - N  (includes commissions, which IBKR already has in cost basis/proceeds).
  4. T is split into: gross realized gains/losses (R&U, trade-date EUR rates — the Vero convention),
     change in unrealized position P/L, and the remainder F = FX on cash/margin balances.
     IBKR's R&U 'Forex' row is NOT booked: in a EUR-base account its FX effect is already inside
     the EUR stock/futures P/L, so adding it double counts (that was the 2025 plug).
  5. Lower of cost or market (KPL 5:6): unrealized losses booked as write-downs, unrealized gains not
     booked (securities at cost; futures gains, already settled in cash, deferred as accrued liability).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Statement

DEFAULT_ACCOUNTS = {
    "cash": ("1910", "Pankkitili / IBKR käteinen (positiiviset saldot)"),
    "collateral": ("1810", "Vakuusarvo välittäjällä (SYEP / right to use)"),
    "securities": ("1440", "Muut osakkeet ja osuudet (vaihtuvat vastaavat)"),
    "unbooked": ("1441", "Kirjaamattomat arvonnousut (KPL 5:6, vähennys)"),
    "prepaid": ("1790", "Siirtosaamiset (korko-/osinkojaksotukset)"),
    "margin_loan": ("2841", "Luottolimiitti / IBKR marginaalilaina (negatiiviset saldot)"),
    "short_pos": ("2845", "Lyhyeksimyydyt arvopaperit (markkina-arvo)"),
    "sru": ("2849", "Velka: arvopapereiden käyttöoikeus (SRU)"),
    "accrued": ("2962", "Siirtovelat (korkojaksotukset)"),
    "fut_deferred": ("2963", "Siirtovelat: avoimien futuurien realisoitumattomat voitot"),
    "transfer": ("1900", "Siirto yhtiön pankkitililtä (sisäinen siirto)"),
    "gains": ("9090", "Luovutusvoitot arvopapereista ja johdannaisista"),
    "dividends": ("9091", "Osinkotuotot"),
    "pil": ("9092", "Muut rahoitustuotot (payment in lieu of dividend)"),
    "int_income": ("9180", "Korkotuotot"),
    "fx_gain": ("9183", "Kurssivoitot"),
    "losses": ("9670", "Luovutustappiot arvopapereista ja johdannaisista"),
    "int_exp": ("9442", "Korkokulut"),
    "int_accrual": ("9443", "Korkokulujen jaksotus (muutos)"),
    "ftt": ("9445", "Transaktioverot (FTT)"),
    "fees": ("9446", "Muut rahoituskulut"),
    "fx_loss": ("9447", "Kurssitappiot"),
    "writedown": ("9698", "Arvonalentumiset vaihtuvien vastaavien arvopapereista"),
    "div_accrual": ("9699", "Osinkojaksotusten muutos"),
    "wht_div": ("9981", "Ulkomaiset lähdeverot osingoista"),
    "wht_int": ("9982", "Ulkomaiset lähdeverot koroista"),
}


@dataclass
class Settings:
    company: str = ""
    fiscal_year: str = ""
    share_category: str = "muu omaisuus"   # or "rahoitusomaisuus" (EVL 9 §) — ask kirjanpitäjä
    opening_writedowns: float = 0.0        # write-down provision at period start (from last year's file)
    opening_unbooked_gains: float = 0.0    # unrealized gains not booked at period start
    evl8a_carryforward: float = 0.0        # prior years' unused share losses (EVL 8 a §)
    wopt_premium_carry: float = 0.0        # OPT-Y2: premiums taxed in earlier years for options closed this year (EUR)
    # OPT-Y8: open written options at year-end — {symbol: "addback" | "deduct" | "fair_value"} (user's choice per option)
    wopt_y8: dict = field(default_factory=dict)
    fair_value_5_2a: bool = False          # company values trading financial instruments at fair value (KPL 5:2a)
    wopt_loss_carry: float = 0.0           # OPT-Y8: written-option book losses added back last year (part of opening_writedowns)
    transaction_fees_override: float | None = None  # negative EUR, e.g. -2458.32
    tax_rate: float = 0.20
    credit_interest_wht: bool = False      # IE interest WHT: treaty 0 % -> reclaim from Ireland by default
    etf_symbols: set[str] = field(default_factory=set)
    treaty_rates: dict = field(default_factory=lambda: {"DK": 0.15, "US": 0.15, "SE": 0.15, "NO": 0.15,
                                                        "DE": 0.15, "NL": 0.15, "CH": 0.10, "GB": 0.0,
                                                        "AU": 0.15, "CA": 0.15, "FR": 0.0})
    accounts: dict = field(default_factory=lambda: dict(DEFAULT_ACCOUNTS))


@dataclass
class SymbolVal:
    asset_class: str
    symbol: str
    realized_profit: float
    realized_loss: float
    unrealized: float
    is_share: bool

    @property
    def writedown(self) -> float:      # positive amount booked as expense
        return max(-self.unrealized, 0.0)

    @property
    def unbooked_gain(self) -> float:  # positive amount not booked
        return max(self.unrealized, 0.0)


@dataclass
class Books:
    st: Statement
    s: Settings
    symbols: list[SymbolVal] = field(default_factory=list)
    v: dict[str, float] = field(default_factory=dict)       # every number used in the workbook
    checks: list[tuple[str, float, float, str]] = field(default_factory=list)  # (name, ours, ibkr, note)
    warnings: list[str] = field(default_factory=list)
    wht_rows: list[dict] = field(default_factory=list)
    wopt_y8: list[dict] = field(default_factory=list)       # OPT-Y8 rows: open written options at year-end
    preliminary: bool = False                               # a required user choice is missing


Y8_CHOICES = {"addback": "Lisätään takaisin (OPT-Y8)",
              "deduct": "Vähennetään kirjanpidon mukaisesti (ei lähdettä)",
              "fair_value": "EVL 27 e § (käypä arvo, KPL 5:2a)"}


def open_written_options(st: Statement) -> list[dict]:
    """Option positions with a negative quantity at period end (written options still open) and their book loss:
    the lower-of-cost write-down (KPL 5:6) from IBKR's unrealized result for the symbol."""
    from .parse_common import OPTION_CLASSES
    qty: dict[str, float] = {}
    for p in st.positions:
        if p.asset_class in OPTION_CLASSES:
            qty[p.symbol] = qty.get(p.symbol, 0.0) + p.quantity
    out = []
    for sym, q in qty.items():
        if q < 0:
            unrl = sum(r.unrealized for r in st.ru if r.symbol == sym and r.asset_class != "Forex")
            out.append({"symbol": sym, "contracts": -q, "unrealized_eur": unrl, "loss_eur": max(-unrl, 0.0)})
    return sorted(out, key=lambda x: x["symbol"])


NON_POSITION_NAV = {"Cash", "Collateral Value", "Securities Right To Use", "Interest Accruals",
                    "Dividend Accruals", "Total", "Futures"}


def classify_transfers(lines) -> list[str]:
    """Label each Deposits & Withdrawals line: 'Talletus', 'Nosto', or 'Peruttu' for a cancellation and
    the transaction it reverses (same amount, opposite sign, closest date on or before). The pair nets to 0."""
    kinds = ["Talletus" if x.amount_eur > 0 else "Nosto" for x in lines]
    for i, x in enumerate(lines):
        d = x.description.lower()
        if "cancel" not in d and "reversal" not in d:
            continue
        cands = [j for j, y in enumerate(lines)
                 if j != i and not kinds[j].startswith("Peru") and abs(y.amount_eur + x.amount_eur) < 0.005
                 and "cancel" not in y.description.lower() and y.date <= x.date]
        if not cands:  # allow a match dated after the cancellation as a fallback
            cands = [j for j, y in enumerate(lines) if j != i and not kinds[j].startswith("Peru")
                     and abs(y.amount_eur + x.amount_eur) < 0.005 and "cancel" not in y.description.lower()]
        if cands:
            j = max(cands, key=lambda k: (lines[k].date, -abs(k - i)))
            kinds[i] = kinds[j] = "Peruttu"
        else:
            kinds[i] = "Peruutus (ei paria)"
    return kinds


def _is_pil(desc: str) -> bool:
    return "payment in lieu" in desc.lower()


def _is_div_wht(desc: str) -> bool:
    d = desc.lower()
    return "dividend" in d or "in lieu" in d


def wht_country(desc: str, ccy: str) -> str:
    m = re.search(r"\s-\s([A-Z]{2})\b", desc)
    if m:
        return m.group(1)
    if "credit interest" in desc.lower():
        return "IE"  # IBKR Ireland withholds Irish interest WHT
    return ccy[:2]


def _div_country(st: Statement, div_desc: str) -> str:
    """Country of a dividend = country code on the matching WHT line (same ISIN), if any."""
    m = re.match(r"(\S+?\(\w+\))", div_desc)
    key = m.group(1) if m else div_desc[:12]
    for x in st.withholding:
        if x.description.startswith(key):
            mm = re.search(r"\s-\s([A-Z]{2})\b", x.description)
            if mm:
                return mm.group(1)
    return ""


def build(st: Statement, s: Settings) -> Books:
    b = Books(st, s)
    v = b.v
    b.warnings += st.warnings
    etfs = s.etf_symbols | st.etf_symbols

    # ---- 1. economic result
    v["nav_start"] = st.nav_start
    v["nav_end"] = st.nav_end
    kinds = classify_transfers(st.deposits)
    v["deposits_in"] = sum(x.amount_eur for x, k in zip(st.deposits, kinds) if k == "Talletus")
    v["withdrawals"] = sum(x.amount_eur for x, k in zip(st.deposits, kinds) if k == "Nosto")
    v["cancelled"] = sum(x.amount_eur for x, k in zip(st.deposits, kinds) if k.startswith("Peru"))
    if any(k == "Peruutus (ei paria)" for k in kinds):
        b.warnings.append("Deposits & Withdrawals: a 'Cancellation' had no matching opposite transaction — check it.")
    v["net_deposits"] = st.deposits_total_eur if st.deposits_total_eur is not None else v["deposits_in"] + v["withdrawals"]
    v["E"] = v["nav_end"] - v["nav_start"] - v["net_deposits"]

    # ---- 2. non-trading items
    v["div_ord"] = sum(x.amount_eur for x in st.dividends if not _is_pil(x.description))
    v["div_pil"] = sum(x.amount_eur for x in st.dividends if _is_pil(x.description))
    v["wht_div"] = sum(x.amount_eur for x in st.withholding if _is_div_wht(x.description))
    v["wht_int"] = sum(x.amount_eur for x in st.withholding if not _is_div_wht(x.description))
    v["int_income"] = sum(x.amount_eur for x in st.interest if x.amount_eur > 0)
    v["int_expense"] = sum(x.amount_eur for x in st.interest if x.amount_eur < 0)
    v["int_accrual_chg"] = st.nav_total("Interest Accruals", "end") - st.nav_total("Interest Accruals", "start")
    v["div_accrual_chg"] = st.nav_total("Dividend Accruals", "end") - st.nav_total("Dividend Accruals", "start")
    v["fees"] = st.fees_total_eur or 0.0
    if s.transaction_fees_override is not None:
        v["ftt"] = -abs(s.transaction_fees_override)
    elif st.transaction_fees_eur is not None:
        v["ftt"] = st.transaction_fees_eur
    elif "Transaction Fees" in st.change_in_nav:
        v["ftt"] = st.change_in_nav["Transaction Fees"]
    else:
        v["ftt"] = 0.0
        b.warnings.append("Transaction fees (e.g. French FTT) not in this statement. If you traded FR/IT/ES "
                          "shares, enter them from the Activity Statement's 'Transaction Fees' — otherwise "
                          "they end up inside the FX line.")
    v["N"] = (v["div_ord"] + v["div_pil"] + v["wht_div"] + v["wht_int"] + v["int_income"] + v["int_expense"]
              + v["int_accrual_chg"] + v["div_accrual_chg"] + v["fees"] + v["ftt"])
    v["T"] = v["E"] - v["N"]

    # ---- 3. trading split
    for r in st.ru:
        if r.asset_class == "Forex":
            continue
        is_share = r.asset_class == "Stocks" and r.symbol not in etfs
        b.symbols.append(SymbolVal(r.asset_class, r.symbol, r.profit, r.loss, r.unrealized, is_share))
    fx = [r for r in st.ru if r.asset_class == "Forex"]
    v["ru_forex_realized"] = sum(r.realized for r in fx)
    v["ru_forex_unrealized"] = sum(r.unrealized for r in fx)
    v["gains"] = sum(x.realized_profit for x in b.symbols)
    v["losses"] = sum(x.realized_loss for x in b.symbols)
    v["unrl_end"] = sum(x.unrealized for x in b.symbols)
    v["unrl_start"] = s.opening_unbooked_gains - s.opening_writedowns
    v["wd_end"] = sum(x.writedown for x in b.symbols)
    v["wd_start"] = s.opening_writedowns
    v["unbooked_end"] = sum(x.unbooked_gain for x in b.symbols)
    v["unbooked_start"] = s.opening_unbooked_gains
    v["unbooked_sec_end"] = sum(x.unbooked_gain for x in b.symbols if x.asset_class != "Futures")
    v["unbooked_fut_end"] = sum(x.unbooked_gain for x in b.symbols if x.asset_class == "Futures")
    v["F"] = v["T"] - (v["gains"] + v["losses"]) - (v["unrl_end"] - v["unrl_start"])
    v["commissions"] = st.commissions_eur if st.commissions_eur is not None else st.change_in_nav.get("Commissions", 0.0)

    # ---- 4. book result
    v["wd_charge"] = -(v["wd_end"] - v["wd_start"])          # negative = expense
    v["book_result"] = (v["gains"] + v["losses"] + v["wd_charge"] + v["F"] + v["N"])
    v["book_result_check"] = v["E"] - (v["unbooked_end"] - v["unbooked_start"])

    # ---- 5. balance sheet (end) from NAV long/short
    nav = st.nav
    cash = nav.get("Cash")
    v["bs_cash"] = cash.end_long if cash else 0.0
    v["bs_margin_loan"] = cash.end_short if cash else 0.0
    v["bs_collateral"] = nav["Collateral Value"].end_total if "Collateral Value" in nav else 0.0
    v["bs_sru"] = nav["Securities Right To Use"].end_total if "Securities Right To Use" in nav else 0.0
    pos_long = sum(r.end_long for k, r in nav.items() if k not in NON_POSITION_NAV)
    pos_short = sum(r.end_short for k, r in nav.items() if k not in NON_POSITION_NAV)
    v["bs_sec_market"] = pos_long
    v["bs_short_market"] = pos_short
    v["bs_unbooked_contra"] = -v["unbooked_sec_end"]
    acc_long = sum(nav[k].end_long for k in ("Interest Accruals", "Dividend Accruals") if k in nav)
    acc_short = sum(nav[k].end_short for k in ("Interest Accruals", "Dividend Accruals") if k in nav)
    v["bs_prepaid"] = acc_long
    v["bs_accrued"] = acc_short
    v["bs_fut_deferred"] = -v["unbooked_fut_end"]
    v["bs_assets"] = v["bs_cash"] + v["bs_collateral"] + v["bs_sec_market"] + v["bs_unbooked_contra"] + v["bs_prepaid"]
    v["bs_liabs"] = v["bs_margin_loan"] + v["bs_sru"] + v["bs_short_market"] + v["bs_accrued"] + v["bs_fut_deferred"]
    v["bs_equity"] = v["bs_assets"] + v["bs_liabs"]
    v["eq_open"] = v["nav_start"] - v["unbooked_start"]
    v["eq_close_calc"] = v["eq_open"] + v["net_deposits"] + v["book_result"]

    # ---- 6. EVL bridge
    v["evl_add_wht"] = -(v["wht_div"] + v["wht_int"])
    fut_wd = sum(x.writedown for x in b.symbols if not x.is_share and x.asset_class != "Stocks")
    etf_wd = sum(x.writedown for x in b.symbols if not x.is_share and x.asset_class == "Stocks")
    share_wd = sum(x.writedown for x in b.symbols if x.is_share)
    _written_options_y8(b, st, s)
    wopt_wd = sum(r["loss_eur"] for r in b.wopt_y8)
    # opening provision attributed to shares, except written-option losses added back last year (OPT-Y8 carry)
    v["evl_add_wd_other"] = fut_wd + etf_wd - wopt_wd
    v["evl_add_wd_shares"] = ((share_wd - (s.opening_writedowns - s.wopt_loss_carry))
                              if s.share_category == "muu omaisuus" else 0.0)
    share_loss = -sum(x.realized_loss for x in b.symbols if x.is_share)
    mo_gains = sum(x.realized_profit for x in b.symbols)
    if s.share_category == "muu omaisuus":
        v["evl8a_excess"] = max(0.0, share_loss - mo_gains)
        headroom = max(0.0, mo_gains - share_loss)
        v["evl8a_use_cf"] = -min(s.evl8a_carryforward, headroom)
    else:
        v["evl8a_excess"] = 0.0
        v["evl8a_use_cf"] = 0.0
    _written_options_y2(b, st, s)
    v["evl_adjust"] = (v["evl_add_wht"] + v["evl_add_wd_other"] + v["evl_add_wd_shares"]
                       + v["evl8a_excess"] + v["evl8a_use_cf"] + v["evl_add_wopt"] + v["evl_ded_wopt"]
                       + v["evl_add_wd_wopt"] + v["evl_ded_wd_wopt"])
    v["taxable"] = v["book_result"] + v["evl_adjust"]
    v["tax_gross"] = max(v["taxable"], 0.0) * s.tax_rate
    # foreign tax credit: dividend WHT by country, capped at Finnish tax on that income
    # credit = min(WHT, treaty rate x gross, Finnish tax on that income); excess over treaty rate is
    # reclaimable from the source state, not creditable in Finland.
    credit = 0.0
    wht_rows: list[dict] = []
    gross_by_country: dict[str, float] = {}
    for d in st.dividends:
        if not _is_pil(d.description):
            c_ = wht_country(d.description + " - " + _div_country(st, d.description), d.currency)
            gross_by_country[c_] = gross_by_country.get(c_, 0.0) + d.amount_eur
    wht_by_country: dict[str, float] = {}
    for x in st.withholding:
        if _is_div_wht(x.description):
            c_ = wht_country(x.description, x.currency)
            wht_by_country[c_] = wht_by_country.get(c_, 0.0) - x.amount_eur
    for c_, w in wht_by_country.items():
        gross = gross_by_country.get(c_, sum(d.amount_eur for d in st.dividends if not _is_pil(d.description)))
        treaty = s.treaty_rates.get(c_, 0.15)
        cr = min(w, treaty * gross, s.tax_rate * gross)
        reclaim = max(0.0, w - treaty * gross)
        credit += cr
        wht_rows.append({"country": c_, "type": "Osinko", "gross": gross, "wht": w,
                         "rate": w / gross if gross else 0.0, "treaty": treaty, "credit": cr, "reclaim": reclaim})
    if v["wht_int"]:
        w = -v["wht_int"]
        cr = min(w, v["int_income"] * s.tax_rate) if s.credit_interest_wht else 0.0
        credit += cr
        wht_rows.append({"country": "IE", "type": "Korko", "gross": v["int_income"], "wht": w,
                         "rate": w / v["int_income"] if v["int_income"] else 0.0, "treaty": 0.0,
                         "credit": cr, "reclaim": w - cr})
    b.wht_rows = wht_rows
    v["tax_credit"] = -min(credit, v["tax_gross"])
    v["tax_net"] = v["tax_gross"] + v["tax_credit"]
    v["net_interest"] = v["int_income"] + v["int_expense"] + v["int_accrual_chg"]
    if -v["net_interest"] > 500_000:
        b.warnings.append("Net interest expense > 500 000 € — EVL 18 a § interest deduction limit may apply.")

    # ---- 7. checks against IBKR's own NAV walk (only in full Activity Statements)
    c = st.change_in_nav
    def chk(name, ours, key, note=""):
        if key in c:
            b.checks.append((name, ours, c[key], note))
    chk("Dividends", v["div_ord"] + v["div_pil"], "Dividends")
    chk("Withholding tax", v["wht_div"] + v["wht_int"], "Withholding Tax")
    chk("Interest", v["int_income"] + v["int_expense"], "Interest")
    if "Other Fees" in c:
        b.checks.append(("Other fees (+ sales tax)", v["fees"], c["Other Fees"] + c.get("Sales Tax", 0.0), ""))
    chk("Transaction fees", v["ftt"], "Transaction Fees")
    chk("Commissions (from trades)", v["commissions"], "Commissions")
    chk("Deposits & withdrawals", v["net_deposits"], "Deposits & Withdrawals")
    if "Mark-to-Market" in c:
        t_ibkr = (c["Mark-to-Market"] + c.get("Commissions", 0) + c.get("Other FX Translations", 0)
                  + (c.get("Change in Dividend Accruals", 0) - v["div_accrual_chg"])
                  + (c.get("Change in Interest Accruals", 0) - v["int_accrual_chg"]))
        b.checks.append(("Trading result T vs IBKR MTM + commissions + FX translations", v["T"], t_ibkr,
                         "Proves the trading line ties to IBKR's MTM walk"))
    if "Ending Value" in c:
        b.checks.append(("NAV end", v["nav_end"], c["Ending Value"], ""))
    for name, ours, ibkr, _ in b.checks:
        if abs(ours - ibkr) > 1.0:
            b.warnings.append(f"Check failed: {name}: ours {ours:,.2f} vs IBKR {ibkr:,.2f}")
    if abs(v["book_result"] - v["book_result_check"]) > 0.01 or abs(v["bs_equity"] - v["eq_close_calc"]) > 0.05:
        b.warnings.append("Internal tie-out failed (book result or balance sheet) — please report")
    return b


def _written_options_y2(b, st: Statement, s: Settings) -> None:
    """OPT-Y2 (EVL 27 d § 1 mom.): premium of a written option that is OTC (not on a regulated / supervised market) or
    runs longer than 18 months (writing date → expiry, OPT-Y5) is income in the year it is written. The books (and
    IBKR) recognise it only on closing, so for such options written this year and open at year-end the premium is
    added in the EVL bridge; the closing year deducts it (user input `wopt_premium_carry`). Options up to 18 months on
    regulated markets: taxation follows the books (OPT-Y1, OPT-Y7) — no adjustment."""
    from datetime import date
    from .personal import REGULATED_EXCHANGES, option_events
    v = b.v
    written: dict = {}
    option_events(st, [], None, written)
    rows = []
    for o in written.get("open", []):
        if not o["same_year"] or o["premium_eur"] is None:
            continue
        ex = st.listing_exch.get(o["symbol"], "")
        otc = bool(ex) and ex.upper() not in REGULATED_EXCHANGES
        long_ = False
        try:
            long_ = (date.fromisoformat(o["expiry"]) - date.fromisoformat(o["opened"])).days > 548
        except (ValueError, TypeError):
            pass
        if otc or long_:
            rows.append(dict(o, reason="OTC / ei säännelty markkina" if otc else "yli 18 kk"))
    b.wopt_y2 = rows
    v["evl_add_wopt"] = sum(r["premium_eur"] for r in rows)
    v["evl_ded_wopt"] = -abs(s.wopt_premium_carry)
    if rows:
        b.warnings.append("Asetettuja optioita (OTC tai yli 18 kk) avoinna tilikauden lopussa: preemiot "
                          f"{v['evl_add_wopt']:,.2f} € lisätty verotettavaan tuloon asetusvuonna (EVL 27 d § 1 mom.). "
                          "Vähennä ne sulkemisvuonna (asetus 'Aiemmin verotetut asetettujen optioiden preemiot').")


def _written_options_y8(b, st: Statement, s: Settings) -> None:
    """OPT-Y8 (proposal, confirm with the kirjanpitäjä — 62N-95): the year-end book loss of a written option that is
    still open (KPL 5:6 write-down / provision) is not deductible before the option is closed, exercised or expires
    (EVL 27 d § 2 and 4 mom.; HE 84/2002) → added back in the EVL bridge, and the amount added back is deducted the
    next year (input `wopt_loss_carry`). Exception: fair-value accounting under KPL 5:2a → EVL 27 e §. The user chooses
    the treatment per option; while the rule is a proposal nothing is preselected: a missing choice adds the loss back
    (the conservative treatment) and marks the result preliminary."""
    v = b.v
    rows, missing = [], []
    for o in open_written_options(st):
        ch = s.wopt_y8.get(o["symbol"]) if isinstance(s.wopt_y8, dict) else None
        if ch == "fair_value" and not s.fair_value_5_2a:
            b.warnings.append(f"{o['symbol']}: EVL 27 e § valittu, mutta yhtiön ei ole ilmoitettu arvostavan "
                              "rahoitusvälineitä käypään arvoon (KPL 5:2a) — valinta ohitettu.")
            ch = None
        if ch not in Y8_CHOICES and o["loss_eur"] > 0:
            missing.append(o["symbol"])
        rows.append(dict(o, choice=ch if ch in Y8_CHOICES else "", applied=ch if ch in Y8_CHOICES else "addback"))
    b.wopt_y8 = rows
    v["evl_add_wd_wopt"] = sum(r["loss_eur"] for r in rows if r["applied"] == "addback")
    v["wd_wopt_deducted"] = sum(r["loss_eur"] for r in rows if r["applied"] != "addback")
    v["evl_ded_wd_wopt"] = -abs(s.wopt_loss_carry)
    if s.wopt_loss_carry and s.wopt_loss_carry > s.opening_writedowns + 0.005:
        b.warnings.append("Edellisellä tilikaudella lisätyt asetettujen optioiden tappiot ovat suuremmat kuin avaavat "
                          "arvonalentumiset — avaaviin arvonalentumisiin kuuluu myös asetettujen optioiden varaus. Tarkista.")
    if missing:
        b.preliminary = True
        b.warnings.append("Avoimia asetettuja optioita tilikauden lopussa ilman valittua käsittelyä: "
                          f"{', '.join(missing)}. Tappio on lisätty takaisin (OPT-Y8, ehdotus) — valitse käsittely.")
    if any(r["applied"] == "deduct" and r["loss_eur"] > 0 for r in rows):
        b.warnings.append("Avoimen asetetun option tilinpäätöstappio vähennetty kirjanpidon mukaisesti: tälle ei ole "
                          "lähdettä (HE 84/2002: realisoitumaton menetys vähennyskelpoinen vain erityissäännöksellä). "
                          "Vahvista kirjanpitäjältä.")
    if any(r["applied"] == "fair_value" for r in rows):
        b.warnings.append("EVL 27 e § (käypä arvo): tämän työkirjan kirjanpito noudattaa alimman arvon periaatetta "
                          "(KPL 5:6). Käypään arvoon arvostettaessa myös realisoitumattomat arvonnousut kirjataan ja "
                          "verotetaan — oikaise pääkirjanpidossa.")
