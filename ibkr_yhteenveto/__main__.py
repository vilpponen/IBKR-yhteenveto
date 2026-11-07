"""CLI: python -m ibkr_yhteenveto STATEMENT [STATEMENT ...] -o out.xlsx [options]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import Settings, build, load, write_workbook


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ibkr_yhteenveto", description=__doc__)
    ap.add_argument("files", nargs="+", help="IBKR Activity Statement (CSV/PDF) and/or Realized Summary PDF")
    ap.add_argument("-o", "--out", default=None, help="output .xlsx (default: <account>_<year>_tilinpaatos.xlsx)")
    ap.add_argument("--share-category", default="muu omaisuus", choices=["muu omaisuus", "rahoitusomaisuus"])
    ap.add_argument("--ftt", type=float, default=None, help="transaction fees / FTT in EUR if missing from statement")
    ap.add_argument("--opening-writedowns", type=float, default=0.0)
    ap.add_argument("--opening-unbooked-gains", type=float, default=0.0)
    ap.add_argument("--evl8a-carryforward", type=float, default=0.0)
    ap.add_argument("--etf", default="", help="comma-separated symbols that are ETFs/funds (not shares)")
    ap.add_argument("--company", default="")
    a = ap.parse_args(argv)

    st = load(a.files)
    s = Settings(company=a.company, share_category=a.share_category,
                 transaction_fees_override=a.ftt, opening_writedowns=a.opening_writedowns,
                 opening_unbooked_gains=a.opening_unbooked_gains, evl8a_carryforward=a.evl8a_carryforward,
                 etf_symbols={x.strip() for x in a.etf.split(",") if x.strip()})
    b = build(st, s)
    out = Path(a.out or f"{st.account}_{st.period_end[:4]}_tilinpaatos.xlsx")
    out.write_bytes(write_workbook(b))
    v = b.v
    print(f"{st.name} {st.account} {st.period_start}..{st.period_end}")
    for k, lab in [("E", "Economic result (NAV)"), ("book_result", "Book result (KPL)"), ("F", "FX, net"),
                   ("taxable", "Taxable income (EVL)"), ("tax_net", "Corporate tax, net")]:
        print(f"  {lab:24s} {v[k]:>14,.2f}")
    for w in b.warnings:
        print("  ! " + w, file=sys.stderr)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
