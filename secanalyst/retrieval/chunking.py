"""Sliding-window chunking inside each section: a chunk never crosses a section boundary."""

from __future__ import annotations

import pandas as pd

CHUNK_COLUMNS = [
    "chunk_id", "filing_id", "ticker", "form", "fiscal_year", "item", "position", "text",
    "n_words", "period_end",
]  # fmt: skip
MIN_WORDS = 10  # sections shorter than this ("None.", cross-references) carry no content


def chunk_sections(sections: pd.DataFrame, words: int = 320, overlap: int = 60) -> pd.DataFrame:
    """Split each section into windows of ``words`` words sharing ``overlap`` words with the
    previous window. chunk_id = ``{ticker}-{form}-{fy}-{item}-{n:04d}``. A ``period_end``
    column on the input is carried through (empty string when absent)."""
    if not 0 <= overlap < words:
        raise ValueError("overlap must be >= 0 and < words")
    step = words - overlap
    rows = []
    for r in sections.itertuples(index=False):
        toks = r.text.split()
        if len(toks) < MIN_WORDS:
            continue
        pe = str(getattr(r, "period_end", "") or "")
        start, n = 0, 0
        while True:
            piece = toks[start : start + words]
            rows.append(
                {
                    "chunk_id": f"{r.ticker}-{r.form}-{r.fiscal_year}-{r.item}-{n:04d}",
                    "filing_id": r.filing_id,
                    "ticker": r.ticker,
                    "form": r.form,
                    "fiscal_year": r.fiscal_year,
                    "item": r.item,
                    "position": n,
                    "text": " ".join(piece),
                    "n_words": len(piece),
                    "period_end": pe,
                }
            )
            if start + words >= len(toks):
                break
            start += step
            n += 1
    return pd.DataFrame(rows, columns=CHUNK_COLUMNS)
