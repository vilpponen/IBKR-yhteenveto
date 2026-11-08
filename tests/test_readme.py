"""README stays in sync with CHANGELOG.md and its in-page links resolve (scripts/readme_sync.py)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("readme_sync", ROOT / "scripts" / "readme_sync.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)


def test_github_slugs():
    assert rs.slug("Mitkä raportit IBKR:stä") == "mitkä-raportit-ibkrstä"
    assert rs.slug("Osakeyhtiö (Oy)") == "osakeyhtiö-oy"
    assert rs.slug("1. Asenna Python 3.10 tai uudempi") == "1-asenna-python-310-tai-uudempi"
    assert rs.anchors("## A\n## A\n```\n## B\n```\n") == {"a", "a-1"}


def test_readme_matches_changelog_and_links_resolve():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert rs.problems(readme, changelog) == []
    assert len(rs.releases(changelog)) == 5
    assert not any("Tulossa" in r for r in rs.releases(changelog))


def test_no_pr_links_in_readme_list():
    assert rs.plain("2026-11-07 — Demo ja ohjeet ([#4](https://github.com/x/y/pull/4))") == "2026-11-07 — Demo ja ohjeet"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme[readme.index(rs.START):readme.index(rs.END)]
    assert "/pull/" not in block


def test_mismatch_detected():
    changelog = "## Tulossa (dev)\n\n## 2026-01-02 — B\n\n## 2026-01-01 — A\n"
    readme = f"## Viimeisimmät muutokset\n{rs.START}\n* 2026-01-01 — A\n{rs.END}\n[x](#puuttuu)\n"
    errs = rs.problems(readme, changelog)
    assert any("differs" in e for e in errs) and any("#puuttuu" in e for e in errs)
