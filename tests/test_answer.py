"""Extractive answers and the Ask page (fixture index + FakeEmbedder: no network)."""

import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from secanalyst.answer.extractive import NO_MATCH, answer, citation, key_sentences
from secanalyst.config import load_settings
from secanalyst.retrieval.embedding import FakeEmbedder
from secanalyst.retrieval.search import Hit, build_index, search

ROOT = Path(__file__).resolve().parents[1]
EMB = FakeEmbedder()
TEXT = (
    "Export controls restrict our ability to sell advanced chips to customers in China. "
    "The company also pays a quarterly dividend to shareholders every year. "
    "A license requirement could prevent shipments of data center products to China. "
    "Our headquarters are located in a leased building in California. "
)


def fixture_index():
    s = pd.DataFrame(
        [{"filing_id": "f1", "ticker": "NVDA", "form": "10-K", "fiscal_year": "2026",
          "item": "1A", "text": TEXT * 3, "period_end": "2026-01-25"},
         {"filing_id": "f2", "ticker": "AAPL", "form": "10-K", "fiscal_year": "2026",
          "item": "7", "text": "Net sales increased due to higher iPhone demand worldwide. " * 6,
          "period_end": "2026-09-26"}]
    )  # fmt: skip
    return build_index(s, EMB, 320, 60)


def test_citation_format():
    h = Hit("c", 0.1, "NVDA", "10-K", "2026", "1A", "t", "2026-01-25")
    assert citation(h) == "NVDA · 10-K FY2026 (period end 2026-01-25) · Item 1A"
    q = Hit("c", 0.1, "AAPL", "10-Q", "2026", "P2-1A", "t", "2026-03-28")
    assert citation(q).endswith("· Part II Item 1A")


def test_every_key_sentence_has_citation():
    idx = fixture_index()
    q = "export controls on chips to China"
    hits = search(idx, q, embedder=EMB)
    sents = key_sentences(q, hits, EMB, n=3)
    assert 1 <= len(sents) <= 3
    assert all(s.citation and s.chunk_id for s in sents)
    assert "Export controls" in sents[0].text
    assert all(s.text in next(h.text for h in hits if h.chunk_id == s.chunk_id) for s in sents)
    assert key_sentences(q, hits, None, n=3)  # keyword-only fallback


def test_out_of_scope_returns_no_match():
    idx = fixture_index()
    a = answer(idx, "What is Apple's share price today?", EMB, score_floor=0.3)
    assert a.message == NO_MATCH and a.hits == [] and a.sentences == []
    pat = load_settings().out_of_scope_patterns
    g = answer(
        idx, "What is Apple's share price today?", EMB, score_floor=0.0, out_of_scope_patterns=pat
    )
    assert g.message == NO_MATCH  # semantically close to real passages: pattern guard
    ok = answer(idx, "export controls on chips to China", EMB, score_floor=0.3)
    assert ok.message is None and ok.hits and ok.sentences
    q = "Why might Tesla's stock price be volatile?"  # no temporal cue: stays in scope
    assert not any(re.search(p, q, re.IGNORECASE) for p in pat)
    for bad in ["current stock price of Tesla", "What is the share price now", "should I buy NVDA"]:
        assert any(re.search(p, bad, re.IGNORECASE) for p in pat), bad


def test_bm25_only_uses_lexical_floor():
    idx = fixture_index()
    assert answer(idx, "What is Apple's share price today?", None, lexical_floor=0.5).message
    assert not answer(idx, "export controls China", None, lexical_floor=0.5).message


def _page(monkeypatch, embedder):
    from app import common

    monkeypatch.setattr(common, "get_index", fixture_index)
    monkeypatch.setattr(common, "get_embedder", lambda: embedder)
    # hashing vectors have lower cosines than bge: use floors suited to the fake embedder
    st_ = common.get_settings().model_copy(update={"score_floor": 0.2})
    monkeypatch.setattr(common, "get_settings", lambda: st_)
    return AppTest.from_file(str(ROOT / "app/pages/1_Ask_the_filings.py"), default_timeout=60)


@pytest.mark.parametrize("embedder", [EMB, None])
def test_ask_page_answers_and_declines(monkeypatch, embedder):
    at = _page(monkeypatch, embedder).run()
    assert not at.exception, [e.value for e in at.exception]
    at.text_input(key="question").set_value("export controls on chips to China").run()
    assert not at.exception, [e.value for e in at.exception]
    body = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.subheader)
    assert "Key sentences (extractive, not AI-written)" in body
    assert "NVDA · 10-K FY2026" in body
    assert bool(at.info) == (embedder is None)  # BM25-only note
    at.text_input(key="question").set_value("What is Apple's share price today?").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("No relevant passage found" in w.value for w in at.warning)
    assert any("Educational project" in c.value for c in at.caption)


from secanalyst.answer.extractive import split_sentences


def test_split_drops_fragments_and_headings():
    frags = [
        "in part by outsourcing partners located in Asia and elsewhere around the world.",
        "(\u201cBroadcom\u201d), a Delaware corporation, designs and supplies many semiconductor products.",
        "Overview and Basis of Presentation Overview Broadcom Inc.",
        "(see the discussion in this section for more detail and other related matters.",
        "This sentence has no terminal punctuation but is otherwise long enough to keep",
    ]
    for f in frags:
        assert split_sentences(f) == [], f
    good = "The company depends heavily on outsourcing partners for most of its production volume."
    assert split_sentences("THE COMPANY AND ITS RISKS " + good) == [good]
    assert split_sentences(good) == [good]
    long = "Overview and Basis of Presentation Overview Broadcom Inc. is a global technology leader in semiconductors."
    out = split_sentences(long)
    assert out and out[0].startswith("Broadcom Inc. is")


def test_split_keeps_balanced_paren_and_quoted_end():
    out = split_sentences(
        "(See Note 4 for details) the company records revenue when control transfers to buyers. "
        'Management called this approach "the most prudent way to account for revenue."'
    )
    assert any(s.endswith('revenue."') for s in out)


def test_key_sentences_skip_near_duplicates():
    a = "Our revenue is concentrated among a small number of customers in fiscal year 2026."
    b = "Our revenue is concentrated among a small number of customers in fiscal year 2025."
    c = "A single customer accounted for most of our net revenue and receivables balance."
    h = Hit("c1", 0.9, "AVGO", "10-K", "2026", "1A", f"{a} {c}", "2026-11-01")
    h2 = Hit("c2", 0.8, "AVGO", "10-K", "2025", "1A", b, "2025-11-02")
    out = key_sentences("revenue concentrated customers", [h, h2], None, n=5)
    texts = [s.text for s in out]
    assert not (a in texts and b in texts)
    assert c in texts


def test_key_sentences_skip_cut_first_sentence_of_later_chunk():
    cut = "Data Protection Commission regulates our privacy compliance across the European Union."
    ok = "We are subject to European Union privacy regulation and regulatory inquiries."
    h = Hit("META-10-K-2025-1A-0003", 0.9, "META", "10-K", "2025", "1A", f"{cut} {ok}", "2025-12-31")
    h0 = Hit("META-10-K-2025-1A-0000", 0.9, "META", "10-K", "2025", "1A", f"{cut} {ok}", "2025-12-31")
    assert [s.text for s in key_sentences("European Union regulation", [h], None)] == [ok]
    assert cut in [s.text for s in key_sentences("European Union regulation", [h0], None)]


def test_key_sentences_near_duplicate_across_years_keeps_latest():
    old = "We refer to customers who purchase products directly from NVIDIA as direct customers, such as AIBs, distributors, ODMs and OEMs."
    new = "We refer to customers who purchase products directly from NVIDIA as direct customers, such as AIBs, distributors, ODMs, OEMs, CSPs and system integrators."
    ho = Hit("N-10-K-2025-7-0000", 0.9, "NVDA", "10-K", "2025", "7", old, "2025-01-26")
    hn = Hit("N-10-K-2026-7-0000", 0.8, "NVDA", "10-K", "2026", "7", new, "2026-01-25")
    out = [s.text for s in key_sentences("direct customers", [ho, hn], None)]
    assert out == [new]


def test_split_drops_short_and_alleging_fragments():
    assert split_sentences("Google finding that Google violated the law in several markets.") == []
    assert split_sentences("Sales rose in all regions.") == []


def test_split_drops_embedded_caps_headings():
    t = "San Jose, California February 4, 2026 REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM To the Stockholders of Alphabet Inc."
    assert split_sentences(t) == []
