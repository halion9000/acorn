"""CSV files for the compliance lists (vendors, risks, controls, audits): one header row, one row per item, and every cell safe to open in a spreadsheet.

A cell that starts with =, +, - or @ (or a tab or carriage return) would be run as a formula by a spreadsheet, so it is given a leading apostrophe. Dates are written as ISO dates, a missing value as an empty cell.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from fastapi import Response

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def cell(value: Any) -> str:
    """One cell as text a spreadsheet will not run (pure)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return "'" + text if text[:1] in _FORMULA else text


def to_csv(headers: list[str], rows: list[list[Any]]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(headers)
    for r in rows:
        w.writerow([cell(v) for v in r])
    return out.getvalue()


def response(name: str, headers: list[str], rows: list[list[Any]]) -> Response:
    """The CSV as a download called ``name``."""
    return Response(content=to_csv(headers, rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
