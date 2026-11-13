"""Application version — the single source of truth (CHANGELOG.md's newest release must match; CI checks it).

MAJOR.MINOR.PATCH, 0.x until ready for real filings (1.0):
  MINOR — new functionality or ANY change that can alter a calculated figure (bug fixes included):
          a workbook made with an older MINOR version may differ → recalculate.
  PATCH — never alters figures: UI text, documentation, installers, CI.
Bumped in the release commit (dev → main), together with dating the CHANGELOG's "Tulossa (dev)" section.
"""
__version__ = "0.11.0"
