"""Red-flag radar: keyword hits per category over 10-K passages, and customer-concentration
percentages parsed from the text."""

from __future__ import annotations

import re

import pandas as pd

from secanalyst.answer.extractive import citation, filing_citation
from secanalyst.retrieval.search import Hit

CATEGORY_LABELS = {
    "customer_concentration": "Customer concentration",
    "litigation": "Litigation",
    "material_weakness": "Material weakness",
    "going_concern": "Going concern",
    "china_geopolitics": "China / geopolitics",
    "ai_regulation": "AI regulation",
    "export_controls": "Export controls",
    "cybersecurity": "Cybersecurity",
}


def risk_citation(ticker: str, fy: str, period_end: str = "") -> str:
    """Citation for a risk taken from a company's 10-K Item 1A."""
    return filing_citation(ticker, "10-K", fy, "1A", period_end)


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
RADAR_COLUMNS = ["ticker", "fy", "category", "hits", "chunk_ids"]


def _pattern(keywords: list[str]) -> re.Pattern:
    """Literal phrases match on word boundaries; ``re:`` keywords are regular expressions."""
    parts = [
        k[3:] if k.startswith("re:") else rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])"
        for k in keywords
    ]
    return re.compile("|".join(parts), re.IGNORECASE)


MIN_CHARS = 300  # shorter passages are headings or cross-references
MAX_LIST_SEPARATORS = 4  # a sentence with this many commas, semicolons or bullets is a list


def _matches(text: str, pat: re.Pattern, exc: re.Pattern | None, item: str = "") -> bool:
    """Keyword in a core sentence: one that is not a long enumeration (a topic that is only one
    entry in a list of ten is not what the passage is about) unless it names the topic twice.
    Short passages and Item 3 'see Note X' pointers never match."""
    if len(text) < MIN_CHARS or (exc and exc.search(text)):
        return False
    if (
        item == "3"
        and re.search(r"\bsee\b.{0,40}\bNote\b", text, re.IGNORECASE)
        and len(text) < 800
    ):
        return False
    for sent in _SENT.split(text):
        n = len(pat.findall(sent))
        if n and (n >= 2 or len(re.findall(r"[,;•]", sent)) < MAX_LIST_SEPARATORS):
            return True
    return False


def radar(chunks: pd.DataFrame, red_flags: dict) -> pd.DataFrame:
    """One row per (ticker, fiscal year, category) with at least one 10-K passage that contains
    one of the category's keywords
    (restricted to the category's Items, minus its exclusions). ``hits`` counts passages;
    ``chunk_ids`` lists them."""
    k = chunks[chunks["form"] == "10-K"]
    rows = []
    for cat, spec in red_flags.items():
        pat = _pattern(spec["keywords"])
        exc = _pattern(["re:" + e for e in spec["exclude"]]) if spec.get("exclude") else None
        items = spec.get("items")
        cand = k if not items else k[k["item"].isin(items)]
        hit = cand[
            [_matches(t, pat, exc, i) for t, i in zip(cand["text"], cand["item"], strict=True)]
        ]
        for (ticker, fy), g in hit.groupby(["ticker", "fiscal_year"]):
            ids = g.sort_values("chunk_id")["chunk_id"].tolist()
            rows.append({"ticker": ticker, "fy": str(fy), "category": cat, "hits": len(ids),
                         "chunk_ids": ids})  # fmt: skip
    return pd.DataFrame(rows, columns=RADAR_COLUMNS).sort_values(
        ["ticker", "fy", "category"], ignore_index=True
    )


_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
_REVENUE = re.compile(r"of\s+(?:our\s+|the\s+Company.s\s+)?(?:total\s+|net\s+|consolidated\s+)*"
                      r"(?:revenue|sales)", re.IGNORECASE)  # fmt: skip
# a single named/anonymous customer: "one customer", "another direct customer", "Customer A"
_TRIGGER = re.compile(
    r"\b(?:one|another)\s+(?:[a-z\-]+\s+){0,2}customer|\bCustomer\s+[A-Z]\b", re.IGNORECASE
)
_GROUP = re.compile(
    r"Customers\s+[A-Z](?:,\s*[A-Z])*,?\s+and\s+[A-Z]\s+represented\s+"
    r"((?:\d{1,3}(?:\.\d+)?%(?:,\s*|\s+and\s+)?)+)"
)
_AGGREGATE = re.compile(
    r"10%\s+or\s+more|more\s+than\s+10%|top\s+(?:five|ten|\d+)|outside\s+(?:of\s+)?the\s+United|headquartered",
    re.IGNORECASE,
)
_YEAR = re.compile(
    r"^(?:For|During|In)\s+(?:each\s+of\s+)?(?:the\s+)?(?:fiscal\s+)?years?\s+(\d{4})",
    re.IGNORECASE,
)


def _sentence_pcts(sent: str) -> list[float]:
    """Percentages attributed to single customers in one sentence (one per customer)."""
    if _AGGREGATE.search(sent) or not _REVENUE.search(sent):
        return []
    out = []
    g = _GROUP.search(sent)
    if g:
        out += [float(x) for x in _PCT.findall(g.group(1))]
    trig = list(_TRIGGER.finditer(sent))
    for n, m in enumerate(trig):
        end = trig[n + 1].start() if n + 1 < len(trig) else len(sent)
        p = _PCT.search(sent, m.end(), end)
        if p:
            out.append(float(p.group(1)))
    return out


def customer_concentration(chunks: pd.DataFrame) -> list[tuple[str, str, float, str]]:
    """``(ticker, fy, percent, citation)``; see ``customer_concentration_detail``."""
    return [r[:4] for r in customer_concentration_detail(chunks)]


def customer_concentration_detail(
    chunks: pd.DataFrame,
) -> list[tuple[str, str, float, str, str]]:
    """``(ticker, fy, percent, citation)`` for every single customer or direct customer
    reported as X% of (total/net) revenue in a 10-K. A sentence that starts "For fiscal year
    YYYY" is booked to that year. Distributor, top-N and geographic shares are ignored."""
    seen, out = set(), []
    k = chunks[chunks["form"] == "10-K"].sort_values(["ticker", "fiscal_year", "item", "chunk_id"])
    for r in k.itertuples(index=False):
        for sent in _SENT.split(r.text):
            for pct in _sentence_pcts(sent):
                y = _YEAR.match(sent.strip())
                fy = y.group(1) if y else str(r.fiscal_year)
                key = (r.ticker, fy, pct)
                if key in seen:
                    continue
                seen.add(key)
                hit = Hit(r.chunk_id, 0.0, r.ticker, r.form, str(r.fiscal_year), r.item, r.text,
                          getattr(r, "period_end", "") or "")  # fmt: skip
                out.append((r.ticker, fy, pct, citation(hit), " ".join(sent.split())))
    return sorted(out, key=lambda x: (x[0], x[1], -x[2]))
