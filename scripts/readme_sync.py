#!/usr/bin/env python3
"""Keep README.md in sync with CHANGELOG.md and check its table of contents.

    python scripts/readme_sync.py           # check (exit 1 on mismatch) — also run by tests/test_readme.py in CI
    python scripts/readme_sync.py --write   # rewrite README's "Viimeisimmät muutokset" list from CHANGELOG.md

"Viimeisimmät muutokset" lists the 5 newest released CHANGELOG entries (the "Tulossa (dev)" section is not a release)
between the <!-- muutokset:alku --> and <!-- muutokset:loppu --> markers. Every in-page link (#anchor) in README must
point to a heading, using GitHub's anchor rules (lowercase, spaces → '-', punctuation dropped, ä/ö kept).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README, CHANGELOG = ROOT / "README.md", ROOT / "CHANGELOG.md"
START, END = "<!-- muutokset:alku -->", "<!-- muutokset:loppu -->"
N = 5


def slug(heading: str) -> str:
    """GitHub heading anchor: drop markdown links/code, lowercase, keep word chars, spaces and '-'."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)       # [text](url) -> text
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)                           # \w is unicode-aware: keeps ä, ö, å
    return text.replace(" ", "-")


def anchors(md: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    in_code = False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(2))
            n = seen.get(s, 0)
            out.add(s if n == 0 else f"{s}-{n}")
            seen[s] = n + 1
    return out


def releases(changelog: str) -> list[str]:
    heads = [m.group(1) for m in re.finditer(r"^## (.+)$", changelog, re.M)]
    return [h for h in heads if re.match(r"\d{4}-\d{2}-\d{2}", h)][:N]


def expected_block(changelog: str) -> str:
    lines = [f"* {h}" for h in releases(changelog)]
    return "\n".join([START, *lines, "", "Kaikki muutokset: [CHANGELOG.md](CHANGELOG.md).", END])


def problems(readme: str, changelog: str) -> list[str]:
    errs = []
    if START not in readme or END not in readme:
        errs.append(f"README: markers {START} / {END} missing")
    else:
        block = readme[readme.index(START):readme.index(END) + len(END)]
        if block != expected_block(changelog):
            errs.append("README 'Viimeisimmät muutokset' differs from the 5 newest CHANGELOG releases "
                        "— run: python scripts/readme_sync.py --write")
    have = anchors(readme)
    for link in re.findall(r"\]\(#([^)]+)\)", readme):
        if link not in have:
            errs.append(f"README: link #{link} has no matching heading")
    return errs


def main(argv: list[str]) -> int:
    readme, changelog = README.read_text(encoding="utf-8"), CHANGELOG.read_text(encoding="utf-8")
    if "--write" in argv:
        if START not in readme or END not in readme:
            print(f"README: add the markers {START} / {END} first", file=sys.stderr)
            return 1
        new = readme[:readme.index(START)] + expected_block(changelog) + readme[readme.index(END) + len(END):]
        if new != readme:
            README.write_text(new, encoding="utf-8")
            print("README.md updated")
        readme = new
    errs = problems(readme, changelog)
    for e in errs:
        print(e, file=sys.stderr)
    if not errs:
        print("README OK")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
