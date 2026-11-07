"""IBKR-yhteenveto: IBKR-raportit -> Suomen verotus (Oy: KPL/EVL, henkilö: OmaVero)."""
from __future__ import annotations

from pathlib import Path

from .books import Books, Settings, build
from .excel import write_workbook
from .model import Statement

__all__ = ["load", "build", "write_workbook", "Settings", "Books", "Statement"]


def load(paths: list[str | Path]) -> Statement:
    """Parse one or more statements (PDF or CSV) of the same account/period and merge them.

    Put the most complete statement first (Activity Statement CSV > Activity PDF > Realized Summary PDF).
    """
    from .parse_csv import parse_csv
    from .parse_pdf import parse_pdf

    stmts = []
    for p in paths:
        p = Path(p)
        if p.suffix.lower() == ".csv":
            stmts.append(parse_csv(p))
        elif p.suffix.lower() == ".pdf":
            stmts.append(parse_pdf(p))
        else:
            raise ValueError(f"Unsupported file type: {p.name} (use IBKR PDF or CSV)")
    # CSVs first: they carry Change in NAV and exact per-line data
    stmts.sort(key=lambda s: 0 if s.source_files[0].lower().endswith(".csv") else 1)
    main = stmts[0]
    for other in stmts[1:]:
        if other.account and main.account and other.account != main.account:
            main.warnings.append(f"Different accounts merged: {main.account} vs {other.account}")
        if other.period_end and main.period_end and other.period_end != main.period_end:
            main.warnings.append(f"Different period ends merged: {main.period_end} vs {other.period_end}")
        main.merge(other)
    tax = main.change_in_nav.get("Sales Tax")
    if tax and not any("sales tax" in f.description.lower() for f in main.fees):
        from .model import CashLine
        main.fees.append(CashLine(main.period_end, main.base_currency, "Sales Tax (ALV IBKR:n palveluista, Change in NAV)",
                                  tax, tax))
        main.fees_total_eur = (main.fees_total_eur or 0.0) + tax
    return main
