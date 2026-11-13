"""62N-93: CLI personal mode, opening lots JSON and exit codes (synthetic data)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from test_opening_lots import Y1, Y2  # noqa: E402


def run(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "ibkr_yhteenveto", *map(str, args)], capture_output=True, text=True,
                          cwd=ROOT)


def test_personal_mode_with_history(tmp_path):
    (tmp_path / "y2025.csv").write_bytes(Y1)
    (tmp_path / "y2026.csv").write_bytes(Y2)
    out = tmp_path / "o.xlsx"
    r = run(tmp_path, tmp_path / "y2026.csv", tmp_path / "y2025.csv", "--personal", "-o", out)
    assert r.returncode == 0 and out.read_bytes()[:2] == b"PK"
    assert "henkilö" in r.stdout and "5,000.00" in r.stdout


def test_unresolved_lots_and_opening_lots_json(tmp_path):
    (tmp_path / "y2026.csv").write_bytes(Y2)
    r = run(tmp_path, tmp_path / "y2026.csv", "--personal", "-o", tmp_path / "a.xlsx")
    assert r.returncode == 2 and "year-start lot without a decision: AAA" in r.stderr and "PRELIMINARY" in r.stderr
    lots = {"version": 1, "choices": {"AAA": {"method": "lots", "lots": [{"date": "2024-05-02", "qty": 100,
                                                                          "cost_eur": 9000}]}}}
    (tmp_path / "erat.json").write_text(json.dumps(lots))
    r = run(tmp_path, tmp_path / "y2026.csv", "--personal", "--opening-lots", tmp_path / "erat.json",
            "-o", tmp_path / "b.xlsx")
    assert r.returncode == 0 and "6,000.00" in r.stdout
