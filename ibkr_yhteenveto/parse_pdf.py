"""Parser for IBKR PDF statements (Realized Summary, Activity Statement — annual or custom).

Strategy: extract text page by page. Full-width tables (NAV, R&U summary, open
positions, forex balances, trades) are read from the whole page. IBKR prints the
cash sections (Interest, Fees, Withholding Tax, Dividends, Deposits & Withdrawals,
Interest Accruals) in two columns, so those pages are split at the column gutter
and read left column, then right column.
"""
from __future__ import annotations

import io

import re
from pathlib import Path

import pdfplumber

from decimal import Decimal

from .model import CashLine, ForexBalance, NavRow, Position, RURow, Statement
from .num import ZERO, check_date, located
from .parse_common import (ASSET_CLASSES, CCY_RE, DATE_RE, convert_groups, finalize_positions,
                           is_num, parse_period, split_label_nums, to_num)

SECTIONS = [
    "Account Information", "Net Asset Value", "Change in NAV", "Mark-to-Market Performance Summary",
    "Realized & Unrealized Performance Summary", "Cash Report", "Open Positions", "Forex Balances",
    "Net Stock Position Summary", "Trades", "Forex P/L Details", "Corporate Actions", "Transfers",
    "Interest", "Fees", "Interest Accruals", "Withholding Tax", "Dividends", "Payment In Lieu Of Dividends",
    "Deposits & Withdrawals", "Change in Dividend Accruals", "Transaction Fees", "Commission Details",
    "Financial Instrument Information", "Codes", "Notes/Legal Notes", "Collateral for Customer Borrowing",
    "Stock Yield Enhancement Program Securities Lent", "Borrow Fee Details", "Sales Tax Details",
    "Broker Interest Paid", "Broker Interest Received",
]
CASH_SECTIONS = {"Interest", "Fees", "Interest Accruals", "Withholding Tax", "Dividends",
                 "Deposits & Withdrawals", "Transaction Fees", "Payment In Lieu Of Dividends",
                 "Change in Dividend Accruals", "Borrow Fee Details", "Sales Tax Details"}
NOISE = re.compile(r"^(Generated:|Page: \d+|.* - [A-Z][a-z]+ \d{1,2}, \d{4} - .*Page: \d+|Help$)")
GUTTER_X = 400  # column split for two-column cash pages (page width 792pt landscape)


def _page_streams(pdf) -> list[str]:
    out: list[str] = []
    for page in pdf.pages:
        right = page.crop((GUTTER_X, 0, page.width, page.height)).extract_text() or ""
        rlines = [l.strip() for l in right.splitlines() if l.strip()]
        if rlines and rlines[0] in CASH_SECTIONS:
            left = page.crop((0, 0, GUTTER_X, page.height)).extract_text() or ""
            out += left.splitlines() + right.splitlines()
        else:
            out += (page.extract_text() or "").splitlines()
        page.close()   # release the page's parsed objects: otherwise memory grows with every page (GBs per statement)
    return [l.strip() for l in out if l.strip() and not NOISE.match(l.strip())]


def _split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    secs: list[tuple[str, list[str]]] = [("_head", [])]
    for l in lines:
        if l in SECTIONS:
            if secs[-1][0] == l:  # repeated title on a continuation page
                continue
            secs.append((l, []))
        else:
            secs[-1][1].append(l)
    return secs


def parse_pdf(path: str | Path | bytes, name: str | None = None) -> Statement:
    """Parse an IBKR PDF from a path, or from bytes in memory (nothing is written to disk)."""
    fname = name or ("statement.pdf" if isinstance(path, (bytes, bytearray)) else Path(path).name)
    with located(file=fname):
        return _parse_pdf(path, name)


def _parse_pdf(path: str | Path | bytes, name: str | None = None) -> Statement:
    if isinstance(path, (bytes, bytearray)):
        src, name = io.BytesIO(path), name or "statement.pdf"
    else:
        src, name = str(path), name or Path(path).name
    st = Statement(source_files=[name])
    with pdfplumber.open(src) as pdf:
        p0 = pdf.pages[0]
        first = p0.extract_text() or ""
        p0.close()
        lines = _page_streams(pdf)
    head = first.splitlines()
    st.title = next((h.strip() for h in head if h.strip() and h.strip() != "Help"), "")
    st.period_start, st.period_end = parse_period(first)

    secs = _split_sections(lines)
    by_name: dict[str, list[list[str]]] = {}
    for name, body in secs:
        by_name.setdefault(name, []).append(body)

    def body(name):  # concatenate all occurrences
        return [l for b in by_name.get(name, []) for l in b]

    with located(section="Account Information"):
        _account(body("Account Information"), st)
    with located(section="Net Asset Value"):
        _nav(body("Net Asset Value") + body("Change in NAV"), st)
    with located(section="Realized & Unrealized Performance Summary"):
        _ru(body("Realized & Unrealized Performance Summary"), st)
    with located(section="Open Positions"):
        _positions(body("Open Positions"), st)
    with located(section="Forex Balances"):
        _forex_bal(body("Forex Balances"), st)
    with located(section="Trades"):
        _trades(body("Trades"), st)
    with located(section="Forex P/L Details"):
        _stock_legs(body("Trades"), body("Forex P/L Details"), st)
    if body("Corporate Actions"):
        st.warnings.append("PDF:ssä on yritystapahtumia (Corporate Actions); ne luetaan vain Activity Statement CSV:stä "
                           "— lisää CSV, jotta splitit ja osakeannit huomioidaan FIFO-laskennassa.")
    for name, attr in [("Interest", "interest"), ("Fees", "fees"), ("Withholding Tax", "withholding"),
                       ("Dividends", "dividends"), ("Deposits & Withdrawals", "deposits"),
                       ("Transaction Fees", "transaction_fee_lines")]:
        b = body(name)
        if not b:
            continue
        with located(section=name):
            cl, total_eur = _cash_section(b, st.base_currency, st.warnings, name)
        setattr(st, attr, cl)
        tot = total_eur if total_eur is not None else sum(x.amount_eur for x in cl)
        {"interest": lambda: setattr(st, "interest_total_eur", tot),
         "fees": lambda: setattr(st, "fees_total_eur", tot),
         "withholding": lambda: setattr(st, "withholding_total_eur", tot),
         "dividends": lambda: setattr(st, "dividends_total_eur", tot),
         "deposits": lambda: setattr(st, "deposits_total_eur", tot),
         "transaction_fee_lines": lambda: setattr(st, "transaction_fees_eur", tot)}[attr]()
    return st


# ---------------------------------------------------------------- sections
def _account(lines, st):
    for l in lines:
        for key, attr in (("Name", "name"), ("Account", "account"), ("Base Currency", "base_currency"),
                          ("Customer Type", "customer_type")):
            if l.startswith(key + " ") and not l.startswith("Account Type") and not l.startswith("Account Capabilities"):
                setattr(st, attr, l[len(key):].strip())


CHANGE_LABELS = ["Starting Value", "Ending Value", "Mark-to-Market", "Deposits & Withdrawals", "Dividends",
                 "Withholding Tax", "Change in Dividend Accruals", "Interest", "Change in Interest Accruals",
                 "Other Fees", "Commissions", "Transaction Fees", "Other FX Translations", "Sales Tax",
                 "Position Transfers", "Internal Transfers", "Advisor Fees", "Broker Fees",
                 "Payment In Lieu Of Dividends", "Corporate Actions", "Other"]
_CH_RE = re.compile(r"(?:^|\s)(" + "|".join(re.escape(x) for x in sorted(CHANGE_LABELS, key=len, reverse=True))
                    + r")\s+(-?[\d,]+\.\d+)$")


def _nav(lines, st):
    for l in lines:
        if l.startswith("Time Weighted"):
            continue
        rest = l
        m = _CH_RE.search(l)
        if m:
            st.change_in_nav[m.group(1)] = to_num(m.group(2))
            rest = l[: m.start()].strip()
        if not rest:
            continue
        toks = rest.split()
        # NAV row: label + 5 numbers (start total, end long, end short, end total, change)
        nums_tail = []
        while toks and is_num(toks[-1]):
            nums_tail.insert(0, toks.pop())
        if len(nums_tail) >= 5 and toks:
            label = " ".join(toks)
            n = [to_num(x) for x in nums_tail[:5]]
            st.nav[label] = NavRow(label, n[0], n[1], n[2], n[3])


def _ru(lines, st):
    cls = ""
    for l in lines:
        if l in ASSET_CLASSES:
            cls = l
            continue
        label, nums, _ = split_label_nums(l, 12)
        if len(nums) < 12 or not label or label.startswith("Total") or label.startswith("Symbol"):
            continue
        _ca, stp, stl, ltp, ltl, _rt, ustp, ustl, ultp, ultl, _ut, _t = nums
        st.ru.append(RURow(cls, label, stp, stl, ltp, ltl, ustp + ultp, ustl + ultl))


def _positions(lines, st):
    groups, cls, ccy = [], "", ""
    for l in lines:
        if l in ASSET_CLASSES:
            cls = l
            continue
        if CCY_RE.match(l):
            ccy = l
            groups.append({"cls": cls, "ccy": ccy, "rows": [], "eur": None})
            continue
        if l.startswith("Total in"):
            _, nums, _ = split_label_nums(l, 3)
            if groups and len(nums) == 3:
                groups[-1]["eur"] = tuple(nums)
            continue
        if l.startswith("Total") or l.startswith("Symbol"):
            continue
        label, nums, _ = split_label_nums(l, 7)
        if len(nums) == 7 and label and groups:
            q, mult, cp, cb, clp, val, un = nums
            groups[-1]["rows"].append(Position(cls, ccy, label, q, mult, cp, cb, clp, val, un))
    finalize_positions(groups, st.base_currency, st)


def _forex_bal(lines, st):
    for l in lines:
        label, nums, _ = split_label_nums(l, 6)
        if len(nums) == 6 and CCY_RE.match(label):
            q, _cp, cbe, _clp, ve, ue = nums
            st.forex_balances.append(ForexBalance(label, q, cbe, ve, ue))


def _trades(lines, st):
    """Collect commissions (EUR) from currency-group totals."""
    cls, ccy, pending = "", "", None
    comm: dict[str, Decimal] = {}

    def add(c, v):
        comm[c] = comm.get(c, ZERO) + v

    for l in lines:
        if l in ASSET_CLASSES:
            cls = l
            continue
        if CCY_RE.match(l):
            ccy = l
            continue
        toks = l.split()
        if not toks or toks[0] != "Total":
            continue
        if l.startswith("Total in "):
            _, nums, _ = split_label_nums(l)
            if pending and len(nums) >= 2:
                add(pending[0], nums[1])
                pending = None
            continue
        if len(toks) > 1 and is_num(toks[1]):  # currency-group total (not 'Total SYMBOL')
            _, nums, _ = split_label_nums(l)
            if len(nums) < 2:
                continue
            if cls == "Forex" or ccy == st.base_currency:
                add(cls, nums[1])            # forex comm is already 'Comm in EUR'
                pending = None
            else:
                pending = (cls, ccy)
    if pending:
        st.warnings.append(f"Trades: commissions for {pending[0]} {pending[1]} had no EUR total")
    if comm:
        st.commissions_by_class = comm
        st.commissions_eur = sum(comm.values())


def _cash_section(lines, base, warnings, section):
    out: list[CashLine] = []
    gt, gte = {}, {}
    section_total_eur = None
    ccy, buf, last = base, [], None
    subtitle = ""
    for l in lines:
        if l.startswith("Date ") or l in ("Base Currency Summary",):
            continue
        if CCY_RE.match(l):
            ccy, buf, last = l, [], None
            continue
        if l.startswith("Total"):
            label, nums, _ = split_label_nums(l)
            if nums:
                if label == "Total":
                    gt[ccy] = nums[-1]
                elif label == "Total in " + base:
                    gte[ccy] = nums[-1]
                elif label.endswith("in " + base):
                    section_total_eur = (section_total_eur or ZERO) + nums[-1]
            buf, last = [], None
            continue
        if DATE_RE.match(l):
            toks = l.split()
            date = check_date(toks[0])
            rest = toks[1:]
            code = ""
            if rest and not is_num(rest[-1]) and len(rest) >= 2 and is_num(rest[-2]):
                code = rest.pop()
            if not rest or not is_num(rest[-1]):
                buf.append(l)
                continue
            amt = to_num(rest.pop())
            desc = " ".join(rest).strip()
            waiting = not desc
            if not desc:
                desc = " ".join(buf)
            if subtitle:
                desc = f"{desc}"
            last = CashLine(date, ccy, desc.strip(), amt)
            last._waiting = waiting  # type: ignore[attr-defined]
            out.append(last)
            buf = []
            continue
        # plain text line: continuation of previous entry or prefix of next
        if last is not None and getattr(last, "_waiting", False) and (
                len(l) < 25 and (l.startswith("(") or l.endswith(")") or " " not in l)):
            last.description = (last.description + " " + l).strip()
            last._waiting = False  # type: ignore[attr-defined]
            continue
        if section == "Fees" and l in ("Other Fees", "Market Data Fees", "Account Fees"):
            subtitle = l
            continue
        buf.append(l)
    convert_groups(out, gt, gte, base, warnings, section)
    if section_total_eur is None:
        # single-currency section: no 'Total X in EUR' line
        if set(gt) <= {base} and gt:
            section_total_eur = sum(gt.values())
        elif gte or gt:
            section_total_eur = sum(gte.get(c, gt[c] if c == base else ZERO) for c in gt)
    return out, section_total_eur


_FXLEG = re.compile(r"^Stock\s+(-?[\d,]+(?:\.\d+)?)\s+(.+?)\s+(\d{4}-\d{2}-\d{2}),\s*([\d:]+)\s+([A-Z]{3})\s+"
                    r"(-?[\d,]*\.?\d+)\s+(-?[\d,]+\.\d+)\s+(-?[\d,]+\.\d+)\s+(-?[\d,]+\.\d+)")


def _stock_legs(trade_lines, fx_lines, st):
    """Exact EUR value of each stock trade: non-base trades from Forex P/L Details ('Proceeds in EUR' of the
    cash leg, at the trade-date rate), base-currency trades from the Trades rows (proceeds + commission)."""
    for l in fx_lines:
        m = _FXLEG.match(l)
        if m:
            qty = to_num(m.group(1))
            # net of commission (the lots of one order add up to proceeds + commission); the commission share is
            # added from the CSV order row in load() when the CSV is also given
            st.stock_legs.append({"date": check_date(m.group(3)), "time": m.group(4), "symbol": m.group(2), "qty": qty,
                                  "ccy": m.group(5), "cash": abs(to_num(m.group(6))),
                                  "eur": abs(to_num(m.group(7))), "exact": True})
    cls, ccy, date = "", "", ""
    for l in trade_lines:
        if l in ASSET_CLASSES:
            cls = l
            continue
        if CCY_RE.match(l):
            ccy = l
            continue
        if DATE_RE.match(l):
            date = check_date(l[:10])
            continue
        if cls != "Stocks" or ccy != st.base_currency or l.startswith("Total"):
            continue
        label, nums, _code = split_label_nums(l, 6)
        if len(nums) == 5:  # price wrapped onto another line
            nums = [nums[0], ZERO] + nums[1:]
        if len(nums) >= 6 and label:
            qty, _px, proceeds, comm, _basis, _rl = nums[-6:]
            st.stock_legs.append({"date": date, "symbol": label, "qty": qty, "ccy": ccy, "comm_eur": abs(comm),
                                  "eur": abs(proceeds + comm) if qty < 0 else abs(proceeds) + abs(comm), "exact": True})
