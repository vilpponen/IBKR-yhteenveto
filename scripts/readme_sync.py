#!/usr/bin/env python3
"""Keep README.md in sync with CHANGELOG.md and check its table of contents.

    python scripts/readme_sync.py           # check (exit 1 on mismatch) — also run by tests/test_readme.py in CI
    python scripts/readme_sync.py --write   # rewrite README's "Viimeisimmät muutokset" list from CHANGELOG.md

CHANGELOG.md has one "## YYYY-MM-DD" heading per date; each release is a "### X.Y.Z — Title ([#N](…))" under it
(the "## Tulossa (dev)" section is not a release). A date must not appear twice, release versions must be strictly
descending, and the newest one must equal ibkr_yhteenveto/version.py's __version__.

README's "Viimeisimmät muutokset" (between <!-- muutokset:alku --> and <!-- muutokset:loppu -->) shows the 5 newest
releases, one line per date: "* **date** — 0.8.0 Title · 0.7.0 Title" (no PR links). Every in-page link (#anchor) in README must
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


DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")


def dates(changelog: str) -> list[str]:
    return [m.group(1) for line in changelog.splitlines() if (m := DATE_RE.match(line))]


def releases(changelog: str) -> list[tuple[str, str]]:
    """(date, release heading) for the N newest releases, newest first."""
    out, date = [], None
    for line in changelog.splitlines():
        if line.startswith("## "):
            m = DATE_RE.match(line)
            date = m.group(1) if m else None
        elif line.startswith("### ") and date:
            out.append((date, line[4:].strip()))
    return out[:N]


VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+) — ")


def plain(heading: str) -> str:
    """Release heading for README: no PR link, version without the dash ('0.8.0 — Demo ([#4](…))' -> '0.8.0 Demo')."""
    h = re.sub(r"\s*\(\[#\d+\]\([^)]*\)\)\s*$", "", heading).strip()
    return VERSION_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}.{m.group(3)} ", h)


def app_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "ibkr_yhteenveto" / "version.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def all_releases(changelog: str) -> list[str]:
    out, date = [], None
    for line in changelog.splitlines():
        if line.startswith("## "):
            date = DATE_RE.match(line)
        elif line.startswith("### ") and date:
            out.append(line[4:].strip())
    return out


def expected_block(changelog: str) -> str:
    by_date: dict[str, list[str]] = {}
    for d, h in releases(changelog):
        by_date.setdefault(d, []).append(plain(h))
    lines = [f"* **{d}** — {' · '.join(titles)}" for d, titles in by_date.items()]
    return "\n".join([START, *lines, "", "Kaikki muutokset: [CHANGELOG.md](CHANGELOG.md).", END])


def problems(readme: str, changelog: str, check_app_version: bool = True) -> list[str]:
    errs = []
    ds = dates(changelog)
    for d in sorted({d for d in ds if ds.count(d) > 1}):
        errs.append(f"CHANGELOG: date {d} appears more than once — put all releases of a day under one '## {d}'")
    if ds != sorted(ds, reverse=True):
        errs.append("CHANGELOG: date headings must be newest first")
    vers = []
    for h in all_releases(changelog):
        m = VERSION_RE.match(h)
        if not m:
            errs.append(f"CHANGELOG: release '{h}' has no version — use '### X.Y.Z — Otsikko'")
        else:
            vers.append(tuple(int(x) for x in m.groups()))
    if vers != sorted(set(vers), reverse=True):
        errs.append("CHANGELOG: release versions must be unique and newest first")
    if vers and check_app_version and ".".join(map(str, vers[0])) != app_version():
        errs.append(f"CHANGELOG: newest release {'.'.join(map(str, vers[0]))} != ibkr_yhteenveto/version.py "
                    f"__version__ {app_version()} — bump the version in the release commit")
    for line in changelog.splitlines():
        if re.match(r"^## \d{4}-\d{2}-\d{2}\s+\S", line):
            errs.append(f"CHANGELOG: '{line}' — use '## date' and put the release title under it as '### title'")
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
