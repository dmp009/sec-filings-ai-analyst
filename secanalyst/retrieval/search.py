"""Hybrid search (BM25 + cosine, reciprocal-rank fusion) and retrieval evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from rank_bm25 import BM25Plus

from secanalyst.retrieval.embedding import Embedder

RRF_K = 60
POOL = 50  # candidates taken from each ranker before fusion
STOP = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "how", "in", "is", "it", "its", "of", "on", "or", "that", "the", "their", "this", "to", "was", "were", "what", "which", "who", "with", "does", "do", "did", "about", "say", "says", "describe", "disclose"]
)  # fmt: skip
FILTER_COLS = {"ticker": "ticker", "form": "form", "fy": "fiscal_year", "item": "item"}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    score: float  # RRF score (ranking only)
    ticker: str
    form: str
    fy: str
    item: str
    text: str
    period_end: str = ""
    relevance: float = 0.0  # absolute: cosine of best vector match, or lexical coverage


class Index:
    def __init__(self, chunks: pd.DataFrame, vectors: np.ndarray | None = None):
        self.chunks = chunks.reset_index(drop=True)
        self.vectors = None if vectors is None else np.asarray(vectors, dtype=np.float16)
        if self.vectors is not None and len(self.vectors) != len(self.chunks):
            raise ValueError("vectors and chunks differ in length")
        self._tokens = [tokenize(t) for t in self.chunks["text"]]
        self._bm25 = BM25Plus(self._tokens) if self._tokens else None

    def save(self, out_dir: Path | str) -> None:
        out_dir = Path(out_dir)
        self.chunks.to_parquet(out_dir / "chunks.parquet", compression="zstd", index=False)
        np.save(out_dir / "vectors.npy", self.vectors)

    @classmethod
    def load(cls, in_dir: Path | str, with_vectors: bool = True) -> Index:
        in_dir = Path(in_dir)
        chunks = pd.read_parquet(in_dir / "chunks.parquet")
        vec = np.load(in_dir / "vectors.npy") if with_vectors else None
        return cls(chunks, vec)


def build_index(sections: pd.DataFrame, embedder: Embedder, words: int, overlap: int) -> Index:
    from secanalyst.retrieval.chunking import chunk_sections

    chunks = chunk_sections(sections, words, overlap)
    vecs = embedder.embed(chunks["text"].tolist()).astype(np.float16)
    return Index(chunks, vecs)


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal-rank fusion: sum of 1 / (k + rank), ranks starting at 1."""
    out: dict[int, float] = {}
    for ranking in rankings:
        for rank, d in enumerate(ranking, start=1):
            out[d] = out.get(d, 0.0) + 1.0 / (k + rank)
    return out


def _mask(chunks: pd.DataFrame, filters: dict | None) -> np.ndarray:
    m = np.ones(len(chunks), dtype=bool)
    for key, val in (filters or {}).items():
        if val is None or val == [] or val == "":
            continue
        vals = val if isinstance(val, (list, tuple, set)) else [val]
        m &= chunks[FILTER_COLS[key]].isin([str(v) for v in vals]).to_numpy()
    return m


def search(
    index: Index,
    query: str,
    filters: dict | None = None,
    k: int = 8,
    embedder: Embedder | None = None,
) -> list[Hit]:
    """Top-k chunks. Without an embedder (or vectors) it is BM25-only; ``relevance`` is then
    the share of distinct query terms found in the chunk."""
    if index._bm25 is None:
        return []
    mask = _mask(index.chunks, filters)
    cand = np.flatnonzero(mask)
    if len(cand) == 0:
        return []
    q = tokenize(query)
    bm = index._bm25.get_scores(q) if q else np.zeros(len(index.chunks))
    bm_order = [int(i) for i in cand[np.argsort(-bm[cand], kind="stable")][:POOL] if bm[i] > 0]
    rankings = [bm_order]
    cos = None
    if embedder is not None and index.vectors is not None:
        cos = index.vectors.astype(np.float32) @ np.asarray(embedder.embed_query(query), "f4")
        rankings.append([int(i) for i in cand[np.argsort(-cos[cand], kind="stable")][:POOL]])
    fused = rrf(rankings)
    top = sorted(fused, key=lambda i: (-fused[i], i))[:k]
    qset = set(q)
    rows = index.chunks
    hits = []
    for i in top:
        if cos is not None:
            rel = float(cos[i])
        else:
            rel = len(qset & set(index._tokens[i])) / len(qset) if qset else 0.0
        r = rows.iloc[i]
        hits.append(
            Hit(r["chunk_id"], fused[i], r["ticker"], r["form"], r["fiscal_year"], r["item"],
                r["text"], r["period_end"], rel)
        )  # fmt: skip
    return hits


def _norm_ws(s: str) -> str:
    return " ".join(s.lower().split())


def is_match(hit: Hit, item: dict) -> bool:
    return (
        hit.ticker == item["ticker"]
        and hit.fy == str(item["fy"])
        and hit.item == str(item["item"])
        and _norm_ws(item["phrase"]) in _norm_ws(hit.text)
    )


def evaluate(
    index: Index,
    eval_set: list[dict],
    embedder: Embedder | None = None,
    filter_keys: tuple[str, ...] = (),
) -> dict:
    """recall@5 = share of questions with a matching chunk in the top 5; MRR over the top 10
    (reciprocal rank of the first match, 0 if none). A match has the expected ticker, fiscal
    year and item and contains the key phrase. ``filter_keys`` (e.g. ("ticker", "fy")) applies
    the question's own values as search filters, as a user would in the app."""
    per = []
    for q in eval_set:
        filters = {k: q[k] for k in filter_keys} or None
        hits = search(index, q["question"], filters, k=10, embedder=embedder)
        rank = next((r for r, h in enumerate(hits, 1) if is_match(h, q)), None)
        per.append(
            {"id": q.get("id"), "question": q["question"], "rank": rank,
             "top_relevance": hits[0].relevance if hits else 0.0}
        )  # fmt: skip
    n = len(per) or 1
    return {
        "recall_at_5": sum(1 for p in per if p["rank"] and p["rank"] <= 5) / n,
        "mrr": sum(1 / p["rank"] for p in per if p["rank"]) / n,
        "per_question": per,
    }
