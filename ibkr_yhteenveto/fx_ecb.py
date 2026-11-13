"""Optional ECB reference rates for personal-mode currency conversion (62N-94).

The user adds the ECB's own history file (eurofxref-hist.csv, from ecb.europa.eu) to the upload: no network calls,
nothing stored. Each foreign-currency trade leg is converted at the rate of its settlement date (Vero 48262 §2.2:
acquisition cost at the acquisition date's rate, sale price at the sale date's rate): T+1 for USD/CAD trades from
28 May 2024, otherwise T+2, weekends skipped (no holiday calendar); a missing day uses the latest earlier rate.
ECB quotes units of currency per 1 EUR.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal

from .num import check_date, dec, located


def is_ecb(text: str) -> bool:
    head = text.lstrip("﻿").split("\n", 1)[0]
    return head.startswith("Date,") and ",USD" in head


def parse_ecb(text: str, name: str = "eurofxref-hist.csv") -> dict[str, dict[str, Decimal]]:
    """ECB history file → {date: {ccy: units per EUR}}. 'N/A' and empty cells (currency not quoted that day) are
    skipped; any other unreadable value or date stops the calculation (InputError)."""
    lines = [l for l in text.lstrip("﻿").splitlines() if l.strip()]
    cols = [c.strip() for c in lines[0].split(",")]
    out: dict[str, dict[str, Decimal]] = {}
    for i, l in enumerate(lines[1:], start=2):
        cells = [c.strip() for c in l.split(",")]
        with located(file=name, section="EKP-kurssit", line=i):
            row = {}
            for c, v in zip(cols[1:], cells[1:]):
                if not c or v in ("", "N/A"):
                    continue
                row[c] = dec(v, f"EKP-kurssi {c}")
                if row[c] <= 0:
                    from .num import fail
                    raise fail(f"EKP-kurssi {c}: kurssin pitää olla positiivinen", v)
            if cells and row:
                out[check_date(cells[0])] = row
    return out


def trim(rates: dict[str, dict[str, Decimal]], ccys: set[str], first: str, last: str) -> dict[str, dict[str, Decimal]]:
    lo = (date.fromisoformat(first) - timedelta(days=14)).isoformat() if first else ""
    hi = (date.fromisoformat(last) + timedelta(days=14)).isoformat() if last else "9999"
    return {d: {c: r for c, r in row.items() if c in ccys} for d, row in rates.items() if lo <= d <= hi}


def settle_date(trade: str, ccy: str) -> str:
    d = date.fromisoformat(trade[:10])
    n = 1 if ccy in ("USD", "CAD") and d >= date(2024, 5, 28) else 2
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d.isoformat()


def rate_on(rates: dict[str, dict[str, Decimal]], days: list[str], ccy: str, day: str) -> Decimal | None:
    i = bisect_right(days, day)
    while i > 0:
        r = rates[days[i - 1]].get(ccy)
        if r:
            return r
        i -= 1
    return None


def convert_legs(legs: list[dict], rates: dict[str, dict[str, Decimal]], base: str, warnings: list[str]) -> list[dict]:
    """Copies of the legs with `eur` / `comm_eur` at the ECB rate of the settlement date (base-currency legs as is)."""
    days = sorted(rates)
    out, missing = [], set()
    for x in legs:
        y = dict(x)
        cash = x.get("cash")
        if x.get("ccy") and x["ccy"] != base and cash:
            r = rate_on(rates, days, x["ccy"], settle_date(x["date"], x["ccy"]))
            if r:
                comm_ccy = x.get("comm_ccy")
                if comm_ccy is None and x.get("comm_eur") is not None and x.get("eur"):
                    comm_ccy = x["comm_eur"] * cash / x["eur"]
                y["eur"], y["fx"] = cash / r, "ECB"
                if comm_ccy is not None:
                    y["comm_eur"] = comm_ccy / r
            else:
                missing.add(x["ccy"])
        out.append(y)
    if missing:
        warnings.append("EKP-kurssi puuttui (" + ", ".join(sorted(missing)) + ") — näille kaupoille käytetty IBKR:n kursseja.")
    return out
