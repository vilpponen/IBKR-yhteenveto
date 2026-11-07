"""Optional checks against your own IBKR statements — never commit real statements.

    IBKR_COMPANY_2025_PDF=... IBKR_PERSONAL_2026_PDF=... IBKR_PERSONAL_2026_CSV=... pytest tests/test_local_real.py

Fill in the expected figures for your own files in tests/local_expected.json (git-ignored), e.g.
    {"company_2025": {"book_result": 123.45, "taxable": 678.9}, "personal_2026": {"tax_net": 1.0}}
"""
import json
import os
from pathlib import Path

import pytest

from ibkr_yhteenveto import Settings, build, load
from ibkr_yhteenveto.personal import PSettings, build_personal

EXP_FILE = Path(__file__).parent / "local_expected.json"
EXP = json.loads(EXP_FILE.read_text()) if EXP_FILE.is_file() else {}


def _files(*envs):
    paths = [os.environ.get(e, "") for e in envs]
    return [p for p in paths if p and Path(p).is_file()]


@pytest.mark.skipif(not _files("IBKR_COMPANY_2025_PDF"), reason="set IBKR_COMPANY_2025_PDF")
def test_company_statement_ties():
    st = load(_files("IBKR_COMPANY_2025_PDF"))
    ftt = EXP.get("company_2025", {}).get("ftt")
    b = build(st, Settings(transaction_fees_override=-abs(ftt) if ftt else None))
    v = b.v
    assert abs(v["book_result"] - v["book_result_check"]) < 0.01
    assert abs(v["bs_equity"] - v["eq_close_calc"]) < 0.05
    for k, val in EXP.get("company_2025", {}).items():
        if k in v:
            assert abs(v[k] - val) < 0.02, k


@pytest.mark.skipif(not _files("IBKR_PERSONAL_2026_PDF"), reason="set IBKR_PERSONAL_2026_PDF (+ _CSV)")
def test_personal_statement():
    st = load(_files("IBKR_PERSONAL_2026_CSV", "IBKR_PERSONAL_2026_PDF"))
    b = build_personal(st, PSettings())
    v = b.v
    assert abs(v["sec_net"] - v["ru_sec_net"]) < 0.02 * max(1.0, abs(v["ru_sec_net"])) + 50
    assert round(v["sec_proceeds"] - v["sec_cost"], 2) == round(v["sec_net"], 2)
    for k, val in EXP.get("personal_2026", {}).items():
        if k in v:
            assert abs(v[k] - val) < 1.0, k
