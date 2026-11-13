"""Exact money arithmetic and strict input (62N-97).

* Every amount is a `decimal.Decimal` at full precision through the whole calculation; rounding happens only at output
  (UI, Excel, reports) with ROUND_HALF_EVEN (owner's decision 13.11.2026).
* Unreadable input stops the calculation with `InputError` naming the file, section, line and value — it never turns
  silently into 0. An empty cell or IBKR's "--" is 0.
"""
from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

D = Decimal
ZERO = Decimal(0)
ONE = Decimal(1)
CENT = Decimal("0.01")
# internal tie-outs (book result vs NAV walk, balance sheet, trial balance): only arithmetic residue is allowed
TIE_TOL = Decimal("0.000001")
# checks against IBKR's own printed totals (IBKR rounds them itself)
IBKR_TOL = CENT


class InputError(ValueError):
    """A value in the input cannot be used. Carries where it was found so the user can fix the file."""

    def __init__(self, message: str, *, file: str = "", section: str = "", line: int | str | None = None,
                 value: object = None):
        self.file, self.section, self.line, self.value = file, section, line, value
        where = " · ".join(x for x in (file, section, f"rivi {line}" if line not in (None, "") else "") if x)
        shown = "" if value is None else f" (arvo: {str(value)[:60]!r})"
        super().__init__(f"{where + ': ' if where else ''}{message}{shown}")


_where: contextvars.ContextVar[dict] = contextvars.ContextVar("ibkr_input_where", default={})


@contextmanager
def located(**kw):
    """Parsers wrap row handling in `with located(file=…, section=…, line=…)` so errors name the spot."""
    token = _where.set({**_where.get(), **kw})
    try:
        yield
    finally:
        _where.reset(token)


def fail(message: str, value: object = None) -> InputError:
    w = _where.get()
    return InputError(message, file=w.get("file", ""), section=w.get("section", ""), line=w.get("line"), value=value)


def dec(x, what: str = "luku") -> Decimal:
    """Strict conversion of a value that is already a number (int, Decimal, numeric string) to a finite Decimal."""
    if isinstance(x, Decimal):
        d = x
    elif isinstance(x, bool):
        raise fail(f"{what}: odotettiin lukua", x)
    elif isinstance(x, int):
        return Decimal(x)
    elif isinstance(x, float):
        d = Decimal(repr(x))          # shortest repr: 0.1 → Decimal('0.1'), not the binary expansion
    elif isinstance(x, str):
        try:
            d = Decimal(x.strip())
        except InvalidOperation:
            raise fail(f"{what}: lukukelvoton luku", x) from None
    else:
        raise fail(f"{what}: odotettiin lukua", x)
    if not d.is_finite():
        raise fail(f"{what}: luku ei ole äärellinen (NaN tai ääretön)", x)
    return d


def decimalize(o):
    """Floats anywhere inside `o` (dataclass, dict, list) → exact Decimal, in place for dataclasses."""
    if isinstance(o, float):
        return dec(o)
    if isinstance(o, dict):
        return {k: decimalize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [decimalize(v) for v in o]
    if hasattr(o, "__dataclass_fields__"):
        for f in o.__dataclass_fields__:
            setattr(o, f, decimalize(getattr(o, f)))
    return o


def opt_dec(x, what: str = "luku") -> Decimal | None:
    return None if x is None else dec(x, what)


def check_date(s: str, what: str = "päivämäärä") -> str:
    """ISO date (YYYY-MM-DD, optionally followed by a time) → the date part; anything else is an input error."""
    try:
        return date.fromisoformat(str(s).strip()[:10]).isoformat()
    except ValueError:
        raise fail(f"{what}: virheellinen päivämäärä", s) from None


def nonneg(x: Decimal, what: str) -> Decimal:
    if x < 0:
        raise fail(f"{what}: negatiivinen arvo ei ole mahdollinen", x)
    return x


def money(x) -> Decimal | None:
    """Presentation rounding: cents, half even. None stays None."""
    if x is None:
        return None
    return dec(x).quantize(CENT, rounding=ROUND_HALF_EVEN)


def money_f(x) -> float | None:
    """Rounded to cents for a JSON response to the UI (display only)."""
    m = money(x)
    return None if m is None else float(m)


# ---- JSON transport of the parsed statement (browser keeps it opaque and sends it back unchanged)
_TAG = "#D:"


def to_jsonable(o):
    """Decimals → tagged strings so the round trip through the browser is exact (JS numbers are binary doubles)."""
    if isinstance(o, Decimal):
        return _TAG + str(o)
    if isinstance(o, dict):
        return {k: to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [to_jsonable(v) for v in o]
    return o


def from_jsonable(o):
    if isinstance(o, str) and o.startswith(_TAG):
        return dec(o[len(_TAG):])
    if isinstance(o, float):
        return dec(o)
    if isinstance(o, dict):
        return {k: from_jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [from_jsonable(v) for v in o]
    return o


def loads(text: str | bytes):
    """JSON from the user or the browser: every non-integer number becomes an exact Decimal; NaN/Infinity rejected."""
    def bad(c):
        raise InputError(f"JSON: luku ei ole äärellinen ({c})")
    return from_jsonable(json.loads(text, parse_float=Decimal, parse_constant=bad))


def _out(o):
    """JSON for UI responses: Decimals as numbers. Money is already rounded (half even) by report.py; quantities
    (shares, contracts, crypto units) keep their digits."""
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, dict):
        return {k: _out(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_out(v) for v in o]
    return o


def response_json(obj, statement_keys=("statement",)) -> bytes:
    """Encode an API response: the parsed statement exactly (tagged), everything else as plain JSON numbers."""
    out = {}
    for k, v in obj.items():
        out[k] = to_jsonable(v) if k in statement_keys else _out(v)
    return json.dumps(out, ensure_ascii=False, allow_nan=False).encode()
