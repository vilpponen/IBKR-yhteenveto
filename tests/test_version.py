"""The version is stamped where users see it: CLI, both workbooks (synthetic fixture)."""
import io
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

from ibkr_yhteenveto import Settings, __version__, build, load, write_workbook
from ibkr_yhteenveto.excel_personal import write_personal_workbook
from ibkr_yhteenveto.personal import PSettings, build_personal

FIX = Path(__file__).parent / "fixtures" / "esimerkki_oy_2025.csv"


def _texts(xlsx: bytes) -> str:
    wb = load_workbook(io.BytesIO(xlsx))
    return "\n".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value)


def test_workbooks_carry_version():
    st = load([FIX])
    assert f"IBKR-yhteenveto {__version__}" in _texts(write_workbook(build(st, Settings())))
    assert f"IBKR-yhteenveto {__version__}" in _texts(write_personal_workbook(build_personal(st, PSettings())))


def test_cli_version():
    out = subprocess.run([sys.executable, "-m", "ibkr_yhteenveto", "--version"], capture_output=True, text=True,
                         cwd=Path(__file__).parent.parent)
    assert out.stdout.strip() == f"IBKR-yhteenveto {__version__}"
