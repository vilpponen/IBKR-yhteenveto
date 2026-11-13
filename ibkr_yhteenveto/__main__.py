"""CLI: python -m ibkr_yhteenveto STATEMENT [STATEMENT ...] [-o out.xlsx] [--personal] [options]

Company (default): KPL bookkeeping + EVL bridge. --personal: OmaVero capital income (FIFO, 9A/16B).
Statements of earlier periods of the same account may be given too: they become lot history (personal mode).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Settings, __version__, build, load, write_workbook
from .books import open_written_options
from .num import ZERO, InputError, dec, loads, nonneg


def _amount(text: str):
    """Command-line euro amount: exact Decimal, must be a finite number ≥ 0."""
    try:
        return nonneg(dec(text.replace(",", "."), "summa"), "summa")
    except InputError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main(argv=None) -> int:
    try:
        return _main(argv)
    except InputError as e:      # unreadable input: say where, never compute with a silent 0
        print(f"VIRHE: {e}", file=sys.stderr)
        return 3


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ibkr_yhteenveto", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"IBKR-yhteenveto {__version__}")
    ap.add_argument("files", nargs="+", help="IBKR Activity Statement (CSV/PDF) and/or Realized Summary PDF")
    ap.add_argument("-o", "--out", default=None, help="output .xlsx (default: <account>_<year>_tilinpaatos/omavero.xlsx)")
    ap.add_argument("--company", default="", help="company name (company mode) or person's name (personal mode)")
    g = ap.add_argument_group("company mode (default)")
    g.add_argument("--share-category", default="muu omaisuus", choices=["muu omaisuus", "rahoitusomaisuus"])
    g.add_argument("--ftt", type=_amount, default=None, help="transaction fees / FTT in EUR if missing from statement")
    g.add_argument("--opening-writedowns", type=_amount, default=ZERO)
    g.add_argument("--opening-unbooked-gains", type=_amount, default=ZERO)
    g.add_argument("--evl8a-carryforward", type=_amount, default=ZERO)
    g.add_argument("--wopt-premium-carry", type=_amount, default=ZERO,
                   help="OPT-Y2: premiums of OTC/>18-month written options taxed in earlier years, closed this year")
    g.add_argument("--wopt-y8", default=None, choices=["addback", "deduct", "fair_value"],
                   help="OPT-Y8 (proposal): treatment of the year-end book loss of written options still open, for all "
                        "of them (addback = add back in EVL, deduct = follow the books, fair_value = EVL 27 e §)")
    g.add_argument("--fair-value-5-2a", action="store_true",
                   help="the company values trading financial instruments at fair value (KPL 5:2a); needed for fair_value")
    g.add_argument("--wopt-loss-carry", type=_amount, default=ZERO,
                   help="OPT-Y8: written-option book losses added back last year (part of --opening-writedowns)")
    g.add_argument("--etf", default="", help="comma-separated symbols that are ETFs/funds (not shares)")
    p = ap.add_argument_group("personal mode")
    p.add_argument("--personal", action="store_true", help="individual: OmaVero capital income instead of company books")
    p.add_argument("--loss-cf", type=_amount, default=ZERO, help="confirmed capital losses from earlier years (EUR)")
    p.add_argument("--include-fx", action="store_true", help="include IBKR's Forex row as currency disposals")
    p.add_argument("--no-presumption", action="store_true", help="never use hankintameno-olettama")
    p.add_argument("--fx-mode", default="ibkr", choices=["ibkr", "ecb"],
                   help="ecb: ECB reference rate of the settlement date (give eurofxref-hist.csv among the files)")
    p.add_argument("--extra-regulated", default="", help="extra regulated exchanges, comma-separated (e.g. ICEEU)")
    p.add_argument("--opening-lots", default=None,
                   help="year-start lots JSON (the web app's 'Vie valinnat' / 'Vuoden lopun erät' export)")
    a = ap.parse_args(argv)

    st = load(a.files)
    if a.personal:
        return _personal(a, st)
    s = Settings(company=a.company, share_category=a.share_category,
                 transaction_fees_override=a.ftt, opening_writedowns=a.opening_writedowns,
                 opening_unbooked_gains=a.opening_unbooked_gains, evl8a_carryforward=a.evl8a_carryforward,
                 wopt_premium_carry=a.wopt_premium_carry,
                 wopt_y8={o["symbol"]: a.wopt_y8 for o in open_written_options(st)} if a.wopt_y8 else {},
                 fair_value_5_2a=a.fair_value_5_2a, wopt_loss_carry=a.wopt_loss_carry,
                 etf_symbols={x.strip() for x in a.etf.split(",") if x.strip()})
    b = build(st, s)
    out = Path(a.out or f"{st.account}_{st.period_end[:4]}_tilinpaatos.xlsx")
    out.write_bytes(write_workbook(b))
    v = b.v
    print(f"IBKR-yhteenveto {__version__} · {st.name} {st.account} {st.period_start}..{st.period_end}")
    for k, lab in [("E", "Economic result (NAV)"), ("book_result", "Book result (KPL)"), ("F", "FX, net"),
                   ("taxable", "Taxable income (EVL)"), ("tax_net", "Corporate tax, net")]:
        print(f"  {lab:24s} {v[k]:>14,.2f}")
    for w in b.warnings:
        print("  ! " + w, file=sys.stderr)
    print(f"-> {out}")
    if b.preliminary:
        print("  ! KESKENERÄINEN: avoimille asetetuille optioille ei ole valittu käsittelyä (--wopt-y8).", file=sys.stderr)
    return 2 if b.preliminary else 0


def _personal(a, st) -> int:
    from .excel_personal import write_personal_workbook
    from .personal import PSettings, build_personal

    choices = {}
    if a.opening_lots:
        data = loads(Path(a.opening_lots).read_text(encoding="utf-8"))
        choices = data.get("choices", data) if isinstance(data, dict) else {}
    s = PSettings(name=a.company, loss_carryforward=a.loss_cf, include_fx=a.include_fx,
                  use_presumption=not a.no_presumption, extra_regulated=a.extra_regulated, opening_choices=choices,
                  fx_mode=a.fx_mode)
    b = build_personal(st, s)
    out = Path(a.out or f"{st.account}_{st.period_end[:4]}_omavero.xlsx")
    out.write_bytes(write_personal_workbook(b))
    v = b.v
    print(f"IBKR-yhteenveto {__version__} · {st.name} {st.account} {st.period_start}..{st.period_end} · henkilö")
    for k, lab in [("sec_gains", "Securities gains"), ("sec_losses", "Securities losses"),
                   ("der_gains", "Derivative gains"), ("der_losses", "Derivative losses"),
                   ("cfd_gains", "CFD gains"), ("capital_income", "Capital income"), ("tax_net", "Tax, net (estimate)")]:
        print(f"  {lab:24s} {v.get(k, ZERO):>14,.2f}")
    unresolved = [o for o in b.opening if "unresolved" in o["methods"]]
    for o in unresolved:
        print(f"  ? year-start lot without a decision: {o['symbol']} ({abs(o.get('opening_qty') or o['qty']):g})",
              file=sys.stderr)
    for w in b.warnings:
        print("  ! " + w, file=sys.stderr)
    if b.preliminary:
        print("  ! PRELIMINARY: decide the year-start lots (--opening-lots) or add earlier statements", file=sys.stderr)
    print(f"-> {out}")
    return 2 if b.preliminary else 0


if __name__ == "__main__":
    raise SystemExit(main())
