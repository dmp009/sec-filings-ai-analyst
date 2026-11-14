"""Checks that a drafted answer is supported by the passages it cites."""

from __future__ import annotations

import re

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> set[str]:
    """Numeric cores of every number in ``text``: "$1.2 billion", "15%" and "2026" give
    "1.2", "15" and "2026" (thousands commas and currency/unit words are dropped)."""
    out = set()
    for m in _NUM.findall(text):
        out.add(m.replace(",", "").rstrip("."))
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
    for n in sorted(numbers(draft.answer) - support):
        problems.append(f"number {n} not found in the cited passages")
    return problems
