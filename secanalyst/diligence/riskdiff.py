"""Risk-factor diff between two consecutive 10-Ks: split Item 1A into risks, match them by
embedding similarity, label each pair new / removed / changed / unchanged."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from secanalyst.retrieval.embedding import Embedder

Status = Literal["new", "removed", "changed", "unchanged"]
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
HEAD_MIN_WORDS, HEAD_MAX_WORDS = 5, 45
HEAD_RATIO = 1.5  # the paragraph after a heading is at least this much longer than the heading
EMBED_WORDS = 160  # title + opening of the body; bge-small reads at most 512 tokens
MIN_1A_CHARS = 300  # shorter = cross-reference or missing, not a risk-factor section


@dataclass(frozen=True)
class Risk:
    title: str
    text: str  # title + body


@dataclass(frozen=True)
class RiskChange:
    status: Status
    prev: Risk | None
    curr: Risk | None
    similarity: float | None


MIN_HEADINGS = 10  # fewer than this in a long section: other layout, paragraph fallback
FALLBACK_MIN_CHARS = 20000
PARA_MIN_WORDS = 30
_SMALL = frozenset(
    [
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "vs",
    ]
)


def _title_case(line: str) -> bool:
    words = [w for w in line.split() if w.lower() not in _SMALL]
    return bool(words) and sum(w[0].isupper() for w in words) / len(words) >= 0.8


def _is_heading_shape(line: str) -> bool:
    n = len(line.split())
    if line.startswith(("•", "-", "*")):
        return False
    if HEAD_MIN_WORDS <= n <= HEAD_MAX_WORDS and line[-1] in ".?":
        return True
    # Title Case line without final punctuation ("We Face Intense Competition"), but not a
    # section label ("Legal and Regulatory Risks", "Risks Related to Our Industry")
    label = line.startswith(("Risks Rel", "RISKS REL")) or (
        n <= 8 and line.split()[-1].lower() in ("risks", "matters", "factors")
    )
    return 4 <= n <= 25 and line[-1] not in ".?:;," and _title_case(line) and not label


def split_risks(item_1a: str) -> list[Risk]:
    """Risk headings in 10-K Item 1A are stand-alone one-sentence lines followed by a clearly
    longer paragraph. Bullet summaries, sub-section labels (no final period) and the
    introduction are skipped; a risk's body runs to the next heading."""
    lines = [ln.strip() for ln in (item_1a or "").split("\n") if ln.strip()]
    heads = []
    for i, ln in enumerate(lines[:-1]):
        longer = len(lines[i + 1].split()) >= HEAD_RATIO * len(ln.split())
        follows_heading = bool(heads) and heads[-1] == i - 1
        if _is_heading_shape(ln) and longer and not follows_heading:
            heads.append(i)
    if len(heads) < MIN_HEADINGS and len(item_1a) > FALLBACK_MIN_CHARS:
        return _paragraph_risks(lines)
    out = []
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        body = [b for b in lines[i + 1 : end] if _is_body(b)]
        out.append(Risk(lines[i], "\n".join([lines[i], *body])))
    return out


def _paragraph_risks(lines: list[str]) -> list[Risk]:
    """Fallback for layouts without stand-alone headings (e.g. Microsoft): each paragraph of
    at least 30 words is a unit titled with its first sentence."""
    out = []
    for ln in lines:
        if len(ln.split()) >= PARA_MIN_WORDS:
            body = ln.lstrip("•- ").strip()
            title = _SENT.split(body)[0]
            if len(title.split()) > 40:
                title = " ".join(title.split()[:40]) + "..."
            out.append(Risk(title, body))
    return out


def _is_body(line: str) -> bool:
    return len(line.split()) > 4 or line.endswith(".")  # drops sub-section labels


def _embed_text(r: Risk) -> str:
    return " ".join(r.text.split()[: EMBED_WORDS + len(r.title.split())])


def _jaccard(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


def diff_risks(
    prev: list[Risk], curr: list[Risk], embedder: Embedder, match: float = 0.90,
    change: float = 0.97, lexical: float = 0.85,
) -> list[RiskChange]:  # fmt: skip
    """One-to-one greedy matching on cosine similarity (best pairs first). A pair at or above
    ``match`` is the same risk: ``unchanged`` when the embedding similarity is at least
    ``change`` and the full texts share at least ``lexical`` of their distinct words (the
    embedding only sees the opening of a risk), else ``changed``.
    Unmatched old risks are ``removed``, unmatched current ones ``new``."""
    if not prev and not curr:
        return []
    sim = np.zeros((len(prev), len(curr)), dtype=np.float32)
    if prev and curr:
        a = embedder.embed([_embed_text(r) for r in prev])
        b = embedder.embed([_embed_text(r) for r in curr])
        sim = a @ b.T
    used_p, used_c, out = set(), set(), []
    for flat in np.argsort(-sim, axis=None, kind="stable"):
        i, j = divmod(int(flat), sim.shape[1])
        if sim[i, j] < match:
            break
        if i in used_p or j in used_c:
            continue
        used_p.add(i), used_c.add(j)
        s = float(sim[i, j])
        same = s >= change and _jaccard(prev[i].text, curr[j].text) >= lexical
        out.append(RiskChange("unchanged" if same else "changed", prev[i], curr[j], s))
    out += [RiskChange("removed", p, None, None) for i, p in enumerate(prev) if i not in used_p]
    out += [RiskChange("new", None, c, None) for j, c in enumerate(curr) if j not in used_c]
    return out


DIFF_COLUMNS = [
    "ticker", "fy_prev", "fy_curr", "status", "prev_title", "prev_text", "curr_title",
    "curr_text", "similarity",
]  # fmt: skip


def diff_filings(
    sections: pd.DataFrame,
    embedder: Embedder,
    match: float,
    change: float,
    lexical: float = 0.85,
) -> tuple[pd.DataFrame, list[str]]:
    """Diff the latest two 10-Ks of every company in ``fact_sections``. A company with fewer
    than two 10-Ks with a usable Item 1A is excluded and named in the returned notes."""
    k = sections[(sections["form"] == "10-K") & (sections["item"] == "1A")]
    rows, notes = [], []
    for ticker, g in k.groupby("ticker"):
        g = g[g["text"].str.len() >= MIN_1A_CHARS].sort_values("fiscal_year")
        if len(g) < 2:
            notes.append(f"{ticker}: excluded, fewer than two 10-Ks with an Item 1A section")
            continue
        p, c = g.iloc[-2], g.iloc[-1]
        for ch in diff_risks(
            split_risks(p["text"]), split_risks(c["text"]), embedder, match, change, lexical
        ):
            rows.append(
                {"ticker": ticker, "fy_prev": str(p["fiscal_year"]), "fy_curr": str(c["fiscal_year"]),
                 "status": ch.status,
                 "prev_title": ch.prev.title if ch.prev else None,
                 "prev_text": ch.prev.text if ch.prev else None,
                 "curr_title": ch.curr.title if ch.curr else None,
                 "curr_text": ch.curr.text if ch.curr else None,
                 "similarity": ch.similarity}
            )  # fmt: skip
    return pd.DataFrame(rows, columns=DIFF_COLUMNS), notes
