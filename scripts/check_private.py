#!/usr/bin/env python3
"""Guard against publishing private data: fails if tracked files contain IBKR account numbers,
statement files, or any word listed in .private-words (git-ignored, one word per line).

    python scripts/check_private.py            # scans files tracked by git (or all files if not a repo)
Install as a pre-commit hook:  ln -sf ../../scripts/check_private.py .git/hooks/pre-commit
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = re.compile(r"\bU\d{7,8}\b")
ALLOWED = {"U0000000"}
BLOCKED_SUFFIX = {".pdf", ".xlsx", ".xls"}
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache"}


def files():
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split("\n")
        return [ROOT / f for f in out if f]
    except Exception:
        return [p for p in ROOT.rglob("*") if p.is_file() and not SKIP & set(p.parts)]


def main() -> int:
    words_file = ROOT / ".private-words"
    words = [w.strip() for w in words_file.read_text().splitlines() if w.strip()] if words_file.is_file() else []
    bad = []
    for p in files():
        rel = p.relative_to(ROOT)
        if rel.name in (".private-words",) or not p.is_file():
            continue
        if p.suffix.lower() in BLOCKED_SUFFIX:
            bad.append(f"{rel}: statement/workbook file must not be committed")
            continue
        if p.suffix.lower() == ".csv" and "fixtures" not in rel.parts:
            bad.append(f"{rel}: CSV outside tests/fixtures (real statement?)")
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in ACCOUNT.finditer(text):
            if m.group(0) not in ALLOWED:
                bad.append(f"{rel}: IBKR account number {m.group(0)}")
        for w in words:
            if w.lower() in text.lower():
                bad.append(f"{rel}: private word '{w}'")
    if bad:
        print("Private data check FAILED:\n  " + "\n  ".join(sorted(set(bad))))
        return 1
    print("Private data check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
