"""Serialise an openpyxl workbook entirely in memory.

openpyxl's own ``Workbook.save()`` writes every worksheet to a temporary file on disk before zipping it, even
when saving to a BytesIO. This writer builds each worksheet in memory instead, so a statement's figures never
touch the disk (tests/test_stateless.py guards this).
"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl.drawing.spreadsheet_drawing import SpreadsheetDrawing
from openpyxl.worksheet._writer import WorksheetWriter
from openpyxl.writer.excel import ExcelWriter


class _MemoryExcelWriter(ExcelWriter):
    def write_worksheet(self, ws):   # same as openpyxl 3.1, with out=BytesIO() instead of a temp file
        ws._drawing = SpreadsheetDrawing()
        ws._drawing.charts = ws._charts
        ws._drawing.images = ws._images
        writer = WorksheetWriter(ws, out=BytesIO())
        writer.write()
        ws._rels = writer._rels
        self._archive.writestr(ws.path[1:], writer.read())
        self.manifest.append(ws)


def workbook_bytes(wb) -> bytes:
    if wb.write_only:
        raise ValueError("write-only workbooks are not supported")
    bio = BytesIO()
    _MemoryExcelWriter(wb, ZipFile(bio, "w", ZIP_DEFLATED, allowZip64=True)).save()
    return bio.getvalue()
