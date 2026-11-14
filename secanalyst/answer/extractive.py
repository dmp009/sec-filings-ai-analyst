"""Extractive answers: key sentences picked from retrieved passages, each with its citation.
Nothing is generated; every sentence is verbatim filing text."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from secanalyst.retrieval.embedding import Embedder
from secanalyst.retrieval.search import Hit, Index, search, tokenize

NO_MATCH = (
    "No relevant passage found in the indexed filings. This tool answers questions about "
    "the text of 10-K and 10-Q filings, not market data such as share prices."
)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
MIN_WORDS = 7
_PART = {"P1": "Part I", "P2": "Part II"}


@dataclass(frozen=True)
class Sentence:
    text: str
    chunk_id: str
    citation: str
    score: float


def _item_label(item: str) -> str:
    if item.startswith("P") and "-" in item:
        part, num = item.split("-", 1)
        return f"{_PART.get(part, part)} Item {num}"
    return f"Item {item}"


def filing_citation(ticker: str, form: str, fy: str, item: str, period_end: str = "") -> str:
    """``NVDA · 10-K FY2026 (period end 2026-01-25) · Item 1A``"""
    pe = f" (period end {period_end})" if period_end else ""
    return f"{ticker} · {form} FY{fy}{pe} · {_item_label(item)}"


def citation(hit: Hit) -> str:
    return filing_citation(hit.ticker, hit.form, hit.fy, hit.item, hit.period_end)


def split_sentences(text: str) -> list[str]:
    out = []
    for s in _SENT.split(text):
        s = s.strip().lstrip("\u2022").strip()
        if len(s.split()) >= MIN_WORDS:
            out.append(s)
    return out


def key_sentences(
    query: str, hits: list[Hit], embedder: Embedder | None, n: int = 5
) -> list[Sentence]:
    """Top ``n`` sentences from the hits: 0.7 * embedding similarity + 0.3 * query-term overlap
    (overlap only when no embedder). At most 2 sentences per passage, no duplicates."""
    cands = [(h, s) for h in hits for s in split_sentences(h.text)]
    if not cands:
        return []
    q = set(tokenize(query))
    overlap = np.array([len(q & set(tokenize(s))) / len(q) if q else 0.0 for _, s in cands])
    if embedder is not None:
        vecs = embedder.embed([s for _, s in cands])
        sim = vecs @ np.asarray(embedder.embed_query(query), dtype=np.float32)
        score = 0.7 * sim + 0.3 * overlap
    else:
        score = overlap
    out, seen, per_chunk = [], set(), {}
    for i in np.argsort(-score, kind="stable"):
        h, s = cands[i]
        if s in seen or per_chunk.get(h.chunk_id, 0) >= 2:
            continue
        seen.add(s)
        per_chunk[h.chunk_id] = per_chunk.get(h.chunk_id, 0) + 1
        out.append(Sentence(s, h.chunk_id, citation(h), float(score[i])))
        if len(out) == n:
            break
    return out


@dataclass(frozen=True)
class Answer:
    hits: list[Hit]
    sentences: list[Sentence]
    message: str | None  # NO_MATCH when nothing clears the floor


def answer(
    index: Index,
    query: str,
    embedder: Embedder | None,
    filters: dict | None = None,
    k: int = 8,
    score_floor: float = 0.3,
    lexical_floor: float = 0.5,
    n: int = 5,
    out_of_scope_patterns: list[str] | tuple[str, ...] = (),
) -> Answer:
    """Search, drop to NO_MATCH for out-of-scope patterns or when the best passage is below the floor (cosine with an
    embedder, query-term coverage in BM25-only mode), else add key sentences."""
    if any(re.search(p, query, re.IGNORECASE) for p in out_of_scope_patterns):
        return Answer([], [], NO_MATCH)  # market-data questions: not answerable from filings
    hits = search(index, query, filters, k=k, embedder=embedder)
    floor = score_floor if embedder is not None and index.vectors is not None else lexical_floor
    if not hits or max(h.relevance for h in hits) < floor:
        return Answer([], [], NO_MATCH)
    return Answer(hits, key_sentences(query, hits, embedder, n), None)
