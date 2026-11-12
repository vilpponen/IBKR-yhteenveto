"""IBKR-yhteenveto: IBKR-raportit -> Suomen verotus (Oy: KPL/EVL, henkilö: OmaVero)."""
from __future__ import annotations

from pathlib import Path

from .books import Books, Settings, build
from .excel import write_workbook
from .model import Statement
from .fx_ecb import is_ecb, parse_ecb, trim
from .version import __version__

__all__ = ["__version__", "load", "build", "write_workbook", "Settings", "Books", "Statement"]


def load(paths: list[str | Path | tuple[str, bytes]]) -> Statement:
    """Parse one or more statements (PDF or CSV) and merge them.

    Files of the latest period are the tax year (CSV and PDF of the same period are merged). Files of earlier,
    non-overlapping periods of the same account become lot history (`history_legs`) for year-start positions.

    Each item is a path, or a ``(filename, bytes)`` pair parsed in memory (nothing is written to disk).
    Put the most complete statement first (Activity Statement CSV > Activity PDF > Realized Summary PDF).
    """
    from .parse_csv import parse_csv
    from .parse_pdf import parse_pdf

    stmts, ecb = [], None
    for p in paths:
        if isinstance(p, tuple):
            name, data = Path(p[0]).name, p[1]
        else:
            name, data = Path(p).name, None
        ext = Path(name).suffix.lower()
        if ext == ".csv":
            text = Path(p).read_text(encoding="utf-8-sig") if data is None else data.decode("utf-8-sig")
            if is_ecb(text):          # ECB reference rates (eurofxref-hist.csv), not a statement
                ecb = parse_ecb(text)
                continue
            stmts.append(parse_csv(text + "\n", name=name))
        elif ext == ".pdf":
            stmts.append(parse_pdf(Path(p) if data is None else data, name=name))
        else:
            raise ValueError(f"Unsupported file type: {name} (use IBKR PDF or CSV)")
    # Statements of earlier periods (same account) are lot history for year-start positions; the latest period is
    # the tax year. Within a period: CSVs first (they carry Change in NAV and exact per-line data).
    if not stmts:
        raise ValueError("Ei IBKR-raporttia — lisää Activity Statement (CSV/PDF); EKP-kurssitiedosto yksin ei riitä.")
    ends = sorted({s.period_end for s in stmts if s.period_end}, reverse=True)
    target_end = ends[0] if ends else ""
    groups: dict[str, list[Statement]] = {}
    for s in stmts:
        key = s.period_end if (s.period_end and s.period_end != target_end and s.period_end < _period_start(stmts, target_end)) else target_end
        groups.setdefault(key, []).append(s)
    main = _merge(groups.pop(target_end))
    for end in sorted(groups):                   # oldest first
        h = _merge(groups[end])
        if h.account and main.account and h.account != main.account:
            main.warnings.append(f"Eri tilin raportti ohitettu erähistoriasta: {h.account}")
            continue
        main.history_legs += [dict(x, period=end) for x in h.stock_legs]
        main.history_periods.append(f"{h.period_start} – {h.period_end}")
        if not h.stock_legs:
            main.warnings.append(f"Aiemman kauden raportista ({h.period_start} – {h.period_end}) ei löytynyt "
                                 "osakekauppoja EUR-määrineen.")
    main.history_legs.sort(key=lambda x: x["date"])
    _check_gaps(main)
    if ecb:
        legs = main.stock_legs + main.history_legs
        dates = sorted(x["date"] for x in legs if x.get("date"))
        main.ecb_rates = trim(ecb, {x.get("ccy", "") for x in legs}, dates[0] if dates else "",
                              dates[-1] if dates else "")
    tax = main.change_in_nav.get("Sales Tax")
    if tax and not any("sales tax" in f.description.lower() for f in main.fees):
        from .model import CashLine
        main.fees.append(CashLine(main.period_end, main.base_currency, "Sales Tax (ALV IBKR:n palveluista, Change in NAV)",
                                  tax, tax))
        main.fees_total_eur = (main.fees_total_eur or 0.0) + tax
    return main


def _period_start(stmts: list[Statement], end: str) -> str:
    starts = [s.period_start for s in stmts if s.period_end == end and s.period_start]
    return min(starts) if starts else end


def _merge(group: list[Statement]) -> Statement:
    group.sort(key=lambda s: 0 if s.source_files[0].lower().endswith(".csv") else 1)
    main = group[0]
    for other in group[1:]:
        if other.account and main.account and other.account != main.account:
            main.warnings.append(f"Different accounts merged: {main.account} vs {other.account}")
        if other.period_end and main.period_end and other.period_end != main.period_end:
            main.warnings.append(f"Different period ends merged: {main.period_end} vs {other.period_end}")
        main.merge(other)
    _leg_commissions(main)
    return main


def _leg_commissions(st: Statement) -> None:
    """PDF Forex P/L lots are net of commission; give each lot its share of the CSV order's commission (EUR at the
    lot's own rate) so the gross sale price is known (hankintameno-olettama is a share of the GROSS price)."""
    if not st.trade_rows:
        return
    rows: dict[tuple, list[dict]] = {}
    day: dict[tuple, list[dict]] = {}
    for r in st.trade_rows:
        rows.setdefault((r["date"], r["time"], r["symbol"]), []).append(r)
        day.setdefault((r["date"], r["symbol"], r["qty"] > 0), []).append(r)
    for leg in st.stock_legs:
        if leg.get("comm_eur") is not None or not leg.get("cash"):
            continue
        cands = [r for r in rows.get((leg["date"], leg.get("time", ""), leg["symbol"]), [])
                 if r["qty"] and (r["qty"] > 0) == (leg["qty"] > 0)]
        if not cands:   # FX lots of one order can carry later timestamps: use that day's orders (same side)
            cands = [r for r in day.get((leg["date"], leg["symbol"], leg["qty"] > 0), []) if r["qty"]]
        if cands:   # several orders in the same second: spread their combined commission by quantity
            q = sum(abs(r["qty"]) for r in cands)
            leg["comm_ccy"] = sum(r["comm"] for r in cands) * abs(leg["qty"]) / q
            leg["comm_eur"] = leg["comm_ccy"] * (leg["eur"] / leg["cash"])


def _check_gaps(main: Statement) -> None:
    """History periods must run up to the tax year without gaps, otherwise trades in the gap are missing."""
    from datetime import date, timedelta
    spans = sorted((p.split(" – ")[0], p.split(" – ")[1]) for p in main.history_periods)
    spans.append((main.period_start, main.period_end))
    for (a0, a1), (b0, _) in zip(spans, spans[1:]):
        try:
            if date.fromisoformat(b0) - date.fromisoformat(a1) > timedelta(days=1):
                main.warnings.append(f"Raporttien välissä on aukko ({a1} → {b0}): sen aikaiset kaupat puuttuvat "
                                     "erähistoriasta. Lisää puuttuvan jakson raportti.")
        except ValueError:
            pass
