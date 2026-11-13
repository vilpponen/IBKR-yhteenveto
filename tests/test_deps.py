"""62N-97: dependencies are installed only from the hash-locked files (exact versions + SHA-256 hashes)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _reqs(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return [b for b in re.split(r"\n(?=[a-zA-Z])", text.split("\n", 1)[1]) if b.strip() and not b.startswith("#")]


def test_every_requirement_pinned_with_hashes():
    for name in ("requirements.txt", "requirements-dev.txt"):
        blocks = _reqs(name)
        assert blocks, name
        for b in blocks:
            head = b.split("\\")[0].strip()
            assert re.match(r"^[A-Za-z0-9_.\-\[\]]+==[^\s;]+", head), f"{name}: not pinned: {head}"
            assert "--hash=sha256:" in b, f"{name}: no hash: {head}"


def test_direct_dependencies_are_locked():
    locked = {b.split("==")[0].lower() for b in _reqs("requirements.txt")}
    for line in (ROOT / "requirements.in").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.split(r"[<>=!~ ]", line.strip())[0].lower() in locked, line


def test_all_install_paths_require_hashes():
    for f in ("run.sh", "run.ps1", ".github/workflows/ci.yml"):
        text = (ROOT / f).read_text(encoding="utf-8-sig")
        installs = [l for l in text.splitlines() if "pip install" in l and not l.strip().startswith("#")]
        assert installs and all("--require-hashes" in l for l in installs), f
