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


def _negative(text: str, m: re.Match) -> bool:
    """Written "-12", "\u221212" (not a range like 2024-2026) or accounting "(12)"."""
    before = text[m.start() - 1] if m.start() else ""
    before2 = text[m.start() - 2] if m.start() > 1 else ""
    after = text[m.end()] if m.end() < len(text) else ""
    if before and before in "-\u2212" and not (before2.isalnum() or (before2 and before2 in ")%")):
        return True
    return before == "(" and after == ")"


def numbers(text: str) -> set[tuple[str, str, bool, bool]]:
    """(value, scale, is_percent, is_negative) for every number in ``text``. "$1.2 billion" and
    "1.2 billion" both give ("1.2", "B", False, False); "12%" and "12 percent" give pct tokens.
    A "$" is ignored, so scale and percent must match exactly."""
    out = set()
    for m in _NUM.finditer(text):
        val, unit = m.groups()
        try:
            v = format(Decimal(val.replace(",", "").rstrip(".,")).normalize(), "f")
        except InvalidOperation:
            continue
        u = (unit or "").lower()
        pct = u in ("%", "percent", "per cent")
        out.add((v, "" if pct else _SCALE.get(u, ""), pct, _negative(text, m)))
    return out


def _supported(tok, support) -> bool:
    """Same value/scale/percent; an answer written negative needs a negative cited number."""
    return any(t[:3] == tok[:3] and (t[3] or not tok[3]) for t in support)


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
    for v, sc, pct, neg in sorted(numbers(draft.answer)):
        if not _supported((v, sc, pct, neg), support):
            problems.append(f"number {'-' if neg else ''}{v}{'%' if pct else sc} not in cited text")
    return problems
