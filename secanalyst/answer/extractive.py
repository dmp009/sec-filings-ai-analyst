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


_HEADING_WORDS = {"Overview", "Presentation", "Summary", "Introduction", "Background", "Highlights"}
_CONNECT = {"and", "of", "the", "for", "to", "in", "on"}
_STARTERS = {"We", "Our", "The", "A", "An", "It", "Failures", "In", "If", "As", "Some", "Many"}
_LEAD_HEADINGS = {"Competition", "Overview", "Seasonality", "Customers", "Suppliers"}
MAX_WORDS = 80
_END = re.compile(r"[.!?][\"”’')]?$")


def _strip_heading(s: str) -> str:
    """Drop a glued heading run ("Overview and Basis of Presentation Overview Broadcom Inc.
    is ...") up to the real subject of the sentence."""
    words = s.split()
    caps = 0
    while caps < len(words) and words[caps].isupper() and len(words[caps]) > 1:
        caps += 1
    if caps >= 3:
        s = " ".join(words[caps:])
    # glued section heading: cut after the last heading word among the first ten words
    words = s.split()
    cut = max(
        (i for i, w in enumerate(words[:10]) if w in _HEADING_WORDS and i > 0), default=None
    )
    if cut is not None and all(w[0].isupper() or w in _CONNECT for w in words[: cut + 1]):
        s = " ".join(words[cut + 1 :])
        words = s.split()
    # Title-Case heading glued to the sentence: "Net Revenue A relatively small ...",
    # "Antitrust Matters We are subject ..."
    last = None
    for i, w in enumerate(words[:16]):
        if i >= 1 and w in _STARTERS:
            last = i
        elif not (w[0].isupper() or w in _CONNECT):
            break
    if last is not None:
        s = " ".join(words[last:])
    words = s.split()
    for i in range(4, min(len(words) - 1, 10)):
        if words[i][0].isupper() and words[i + 1] in ("is", "are", "was", "were"):
            if all(x[0].isupper() or x in _CONNECT for x in words[:i]):
                s = " ".join(words[i:])
            break
    words = s.split()
    if len(words) > 3 and words[0] in _LEAD_HEADINGS and words[1][0].isupper():
        s = " ".join(words[1:])
    return s.strip()


def _valid(s: str) -> bool:
    first = next((ch for ch in s if ch.isalpha()), "")
    if not first or first.islower() or "\u2022" in s or len(s.split()) > MAX_WORDS:
        return False
    if s.startswith("(") and s.count(")") != s.count("("):
        return False
    if s.startswith(("(\u201c", '("')):
        return False
    if not _END.search(s):
        return False
    head = s.split()[:3]
    return not (len(head) == 3 and all(w.isupper() for w in head if any(c.isalpha() for c in w)))


def split_sentences(text: str) -> list[str]:
    out = []
    for s in _SENT.split(text):
        s = s.strip().lstrip("\u2022").strip()
        s = _strip_heading(s)
        if len(s.split()) >= MIN_WORDS and _valid(s):
            out.append(s)
    return out


def _position(chunk_id: str) -> int:
    tail = chunk_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _jaccard(a: str, b: str) -> float:
    """Token-set Jaccard with numbers (years, amounts) ignored."""
    x = {t for t in tokenize(a) if not any(c.isdigit() for c in t)}
    y = {t for t in tokenize(b) if not any(c.isdigit() for c in t)}
    return len(x & y) / len(x | y) if x | y else 0.0


def key_sentences(
    query: str, hits: list[Hit], embedder: Embedder | None, n: int = 5
) -> list[Sentence]:
    """Top ``n`` sentences from the hits: 0.7 * embedding similarity + 0.3 * query-term overlap
    (overlap only when no embedder). At most 2 sentences per passage, no duplicates."""
    cands = []
    for h in hits:
        sents = split_sentences(h.text)
        # overlap means a chunk after the first may begin mid-sentence: skip its first sentence
        if sents and _position(h.chunk_id) > 0 and h.text.startswith(sents[0][:30]):
            sents = sents[1:]
        cands += [(h, s) for s in sents]
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
    out, seen, per_chunk, fys = [], set(), {}, []
    for i in np.argsort(-score, kind="stable"):
        h, s = cands[i]
        if s in seen or per_chunk.get(h.chunk_id, 0) >= 2:
            continue
        dup = next(
            (
                j
                for j, o in enumerate(out)
                if _jaccard(s, o.text) >= (0.7 if fys[j] != h.fy else 0.8)
            ),
            None,
        )
        if dup is not None:
            if h.fy > fys[dup] and out[dup].text != s:  # keep the latest fiscal year
                out[dup] = Sentence(s, h.chunk_id, citation(h), float(score[i]))
                fys[dup] = h.fy
                seen.add(s)
            continue
        seen.add(s)
        per_chunk[h.chunk_id] = per_chunk.get(h.chunk_id, 0) + 1
        out.append(Sentence(s, h.chunk_id, citation(h), float(score[i])))
        fys.append(h.fy)
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
