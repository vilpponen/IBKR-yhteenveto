"""Helpers shared by the PDF and CSV parsers."""
from __future__ import annotations

import re
from datetime import datetime

from decimal import Decimal, InvalidOperation

from .model import CashLine, Position, Statement
from .num import ZERO, dec, fail

NUM_RE = re.compile(r"^\(?-?[\d,]*\.?\d+\)?%?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_CCYS = ("EUR USD GBP CHF SEK NOK DKK JPY HKD AUD CAD NZD SGD CNH CNY PLN CZK HUF ILS MXN ZAR "
         "TRY KRW INR TWD THB RUB BRL AED SAR KWD")
CCY_RE = re.compile(r"^(?:" + "|".join(_CCYS.split()) + r")$")
COUNTRY_RE = re.compile(r"\s-\s([A-Z]{2})\b")

ASSET_CLASSES = {
    "Stocks", "Futures", "Forex", "Equity and Index Options", "Options On Futures",
    "Options", "CFDs", "Bonds", "Warrants", "Structured Products", "Mutual Funds",
    "Crypto", "Cryptocurrency", "Treasury Bills", "Futures Options", "Index CFDs",
    "Forex CFDs", "Metals", "Stock Yield Enhancement Program",
}
# CFDs (hinnanerosopimukset): for individuals gains are capital income, losses are not deductible (Vero)
CFD_CLASSES = {"CFDs", "Index CFDs", "Forex CFDs"}
# Crypto assets (IBKR via Paxos / Zero Hash / OSL)
CRYPTO_CLASSES = {"Crypto", "Cryptocurrency"}
# Options on shares/indices (exercise/assignment delivers shares or cash). Futures options are not handled here.
OPTION_CLASSES = {"Equity and Index Options", "Options", "Index Options"}
# IBKR Codes table: tax lot-matching methods other than FIFO
NON_FIFO_CODES = {"LI", "HC", "ML", "MLG", "MLL", "MSG", "MSL", "SL"}


def codes(code: str) -> set[str]:
    """'C;Ex;P' -> {'C', 'Ex', 'P'}"""
    return {c.strip() for c in str(code or "").replace(",", ";").split(";") if c.strip()}


def is_num(tok: str) -> bool:
    return bool(NUM_RE.match(tok)) and any(c.isdigit() for c in tok)


def to_num(tok) -> Decimal:
    """IBKR number token → exact Decimal. Empty cell, '-' or '--' = 0; '(1,234.50)' = -1234.50; '12%' = 12.
    Anything else that is not a finite number stops the calculation (InputError with file/section/line)."""
    if tok is None:
        return ZERO
    if isinstance(tok, (int, float, Decimal)) and not isinstance(tok, bool):
        return dec(tok)
    raw = str(tok)
    s = raw.strip().replace(",", "").replace("%", "")
    if not s or s in ("-", "--"):
        return ZERO
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = Decimal(s)
    except InvalidOperation:
        raise fail("lukukelvoton luku", raw) from None
    if not v.is_finite():
        raise fail("luku ei ole äärellinen (NaN tai ääretön)", raw)
    return -v if neg else v


def split_label_nums(line: str, n: int | None = None):
    """Split 'LABEL n1 n2 ... [CODE]' -> (label, [floats], code).

    If n is given, takes exactly the last n numeric tokens (skipping a trailing
    non-numeric code); everything before them is the label.
    """
    toks = line.split()
    code = ""
    # trailing code tokens (e.g. 'C;P', 'Po')
    while toks and not is_num(toks[-1]) and n is not None:
        code = toks.pop() + (" " + code if code else "")
        if len(code) > 20:
            break
    nums = []
    while toks and is_num(toks[-1]) and (n is None or len(nums) < n):
        nums.insert(0, to_num(toks.pop()))
    return " ".join(toks), nums, code.strip()


def parse_period(text: str):
    """'August 6, 2025 - December 31, 2025' or 'January 1, 2025 - December 31, 2025'."""
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s*-\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if not m:
        m2 = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        if m2:
            d = datetime.strptime(m2.group(1), "%B %d, %Y").date().isoformat()
            return d, d
        return "", ""
    a = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    b = datetime.strptime(m.group(2), "%B %d, %Y").date().isoformat()
    return a, b


def convert_groups(lines: list[CashLine], group_tot: dict, group_tot_eur: dict, base: str,
                   warnings: list[str], section: str) -> None:
    """Convert each line to EUR using the currency group's Total in EUR / Total ratio."""
    for ln in lines:
        if ln.currency == base:
            ln.amount_eur = ln.amount
            continue
        t, te = group_tot.get(ln.currency), group_tot_eur.get(ln.currency)
        if t and te is not None and t != 0:
            ln.amount_eur = ln.amount * te / t
        else:
            ln.amount_eur = ZERO
            warnings.append(f"{section}: no EUR total for {ln.currency}; line '{ln.description}' not converted")


def finalize_positions(groups: list[dict], base: str, st: Statement) -> None:
    """groups: [{'cls','ccy','rows':[Position], 'eur': (cost,value,unrl) or None}]"""
    for g in groups:
        rows: list[Position] = g["rows"]
        if not rows:
            continue
        if g["ccy"] == base:
            for p in rows:
                p.cost_basis_eur, p.value_eur, p.unrealized_eur = p.cost_basis, p.value, p.unrealized
        else:
            eur = g.get("eur")
            tc = sum(p.cost_basis for p in rows)
            tv = sum(p.value for p in rows)
            if not eur:
                st.warnings.append(f"Open Positions: no 'Total in EUR' for {g['cls']} {g['ccy']}")
                continue
            ec, ev, _eu = eur
            for p in rows:
                p.cost_basis_eur = p.cost_basis * ec / tc if tc else ZERO
                p.value_eur = p.value * ev / tv if tv else ZERO
                p.unrealized_eur = p.value_eur - p.cost_basis_eur
        st.positions += rows
