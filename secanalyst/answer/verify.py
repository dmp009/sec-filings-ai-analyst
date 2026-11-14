"""Checks that a drafted answer is supported by the passages it cites."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUM = re.compile(
    r"(?:\$|USD\s?)?(\d[\d,]*(?:\.\d+)?)\s*"
    r"(%|percent|per cent|thousand|million|billion|trillion|bn|m|b)?(?![a-z])",
    re.IGNORECASE,
)
_SCALE = {"thousand": "K", "million": "M", "m": "M", "billion": "B", "bn": "B", "b": "B",
          "trillion": "T"}  # fmt: skip


def numbers(text: str) -> set[tuple[str, str, bool]]:
    """(value, scale, is_percent) for every number in ``text``. "$1.2 billion" and "1.2 billion"
    both give ("1.2", "B", False); "12%" and "12 percent" give ("12", "", True); a bare year
    gives (2026, "", False). A "$" is ignored, so scale and percent must match exactly."""
    out = set()
    for val, unit in _NUM.findall(text):
        try:
            v = format(Decimal(val.replace(",", "").rstrip(".,")).normalize(), "f")
        except InvalidOperation:
            continue
        u = unit.lower()
        out.add((v, "" if u in ("%", "percent", "per cent") else _SCALE.get(u, ""),
                 u in ("%", "percent", "per cent")))  # fmt: skip
    return out


def verify_answer(draft, hits) -> list[str]:
    """Problems found in ``draft`` (an object with .answer and .citations); [] means verified."""
    by_id = {h.chunk_id: h for h in hits}
    cites = list(draft.citations or [])
    if not cites:
        return ["no citations"]
    problems = [f"citation {c} was not retrieved" for c in cites if c not in by_id]
    if problems:
        return problems
    support = set()
    for c in cites:
        support |= numbers(by_id[c].text)
    for v, sc, pct in sorted(numbers(draft.answer) - support):
        problems.append(f"number {v}{'%' if pct else sc} not found in the cited passages")
    return problems
