"""Chunking, hybrid search and evaluation (FakeEmbedder only: no network)."""

import pandas as pd
import pytest

from secanalyst.config import REPO_ROOT
from secanalyst.retrieval.chunking import chunk_sections
from secanalyst.retrieval.embedding import FakeEmbedder
from secanalyst.retrieval.search import Index, build_index, evaluate, rrf, search

EMB = FakeEmbedder()


def sec(ticker, fy, item, text, form="10-K"):
    return {"filing_id": f"{ticker}{fy}", "ticker": ticker, "form": form, "fiscal_year": fy,
            "item": item, "text": text, "period_end": "2026-01-25"}  # fmt: skip


def test_chunk_overlap_and_boundaries():
    a = " ".join(f"a{i}" for i in range(100))
    b = " ".join(f"b{i}" for i in range(30))
    ch = chunk_sections(pd.DataFrame([sec("X", "2026", "1A", a), sec("X", "2026", "7", b)]), 40, 10)
    one = ch[ch["item"] == "1A"]
    assert list(one["chunk_id"])[:2] == ["X-10-K-2026-1A-0000", "X-10-K-2026-1A-0001"]
    w = [t.split() for t in one["text"]]
    assert all(w[i][-10:] == w[i + 1][:10] for i in range(len(w) - 1))
    assert w[-1][-1] == "a99" and all(len(x) <= 40 for x in w)
    assert all(t.split()[0].startswith("b") for t in ch[ch["item"] == "7"]["text"])
    assert all(("a" in t.split()[0]) == (i == "1A") for t, i in zip(ch["text"], ch["item"]))


def test_chunk_skips_tiny_sections():
    ch = chunk_sections(pd.DataFrame([sec("X", "2026", "1B", "None.")]), 40, 10)
    assert ch.empty


def toy_index():
    s = [
        sec("AAA", "2026", "1A", "export controls on advanced chips to China restrict sales " * 3),
        sec("BBB", "2026", "1A", "cloud competition pricing pressure from rival providers " * 3),
        sec("BBB", "2025", "7", "revenue growth driven by cloud demand and export volumes " * 3),
        sec("CCC", "2026", "10-Q", "quarterly dividend declared by the board of directors " * 3, "10-Q"),
    ]  # fmt: skip
    return build_index(pd.DataFrame(s), EMB, 320, 60)


def test_filters_restrict_results():
    idx = toy_index()
    assert all(
        h.ticker == "BBB" for h in search(idx, "cloud export", {"ticker": "BBB"}, embedder=EMB)
    )
    hits = search(idx, "cloud export", {"ticker": "BBB", "fy": "2025"}, embedder=EMB)
    assert [h.fy for h in hits] == ["2025"]
    assert search(idx, "cloud", {"form": "10-Q"}, embedder=EMB)[0].ticker == "CCC"
    assert search(idx, "cloud", {"ticker": "ZZZ"}, embedder=EMB) == []


def test_search_top_hit_and_bm25_only():
    idx = toy_index()
    assert search(idx, "export controls China chips", embedder=EMB)[0].ticker == "AAA"
    h = search(idx, "export controls China chips")[0]  # BM25-only fallback
    assert h.ticker == "AAA" and 0 < h.relevance <= 1
    assert search(idx, "zzzzqq", embedder=EMB)[0].relevance < 0.1


def test_rrf_prefers_bm25_first_vector_second():
    # doc 1: BM25 #1, vectors #2; doc 3: BM25 #3, vectors #1
    f = rrf([[1, 2, 3], [3, 1, 2]])
    assert f[1] == pytest.approx(1 / 61 + 1 / 62)
    assert f[3] == pytest.approx(1 / 63 + 1 / 61)
    assert max(f, key=f.get) == 1 and f[1] > f[3]


def test_evaluate_exact_on_toy_set():
    idx = toy_index()
    es = [
        {"id": "a", "question": "export controls China chips", "ticker": "AAA", "fy": "2026",
         "item": "1A", "phrase": "export controls"},
        {"id": "b", "question": "cloud competition pricing", "ticker": "BBB", "fy": "2026",
         "item": "1A", "phrase": "pricing pressure"},
        {"id": "c", "question": "quarterly dividend", "ticker": "CCC", "fy": "2026",
         "item": "7", "phrase": "dividend"},  # wrong item: never matches
        {"id": "d", "question": "cloud competition pricing", "ticker": "BBB", "fy": "2026",
         "item": "1A", "phrase": "no such phrase"},
    ]  # fmt: skip
    r = evaluate(idx, es, EMB)
    assert [p["rank"] for p in r["per_question"]] == [1, 1, None, None]
    assert r["recall_at_5"] == 0.5 and r["mrr"] == 0.5


def test_index_roundtrip_float16(tmp_path):
    idx = toy_index()
    idx.save(tmp_path)
    back = Index.load(tmp_path)
    assert back.vectors.dtype == "float16" and len(back.chunks) == len(idx.chunks)
    assert search(back, "export controls", embedder=EMB)[0].ticker == "AAA"


SNAP = REPO_ROOT / "data" / "snapshot"
needs_index = pytest.mark.skipif(not (SNAP / "chunks.parquet").exists(), reason="no index yet")


@needs_index
def test_index_aligned_and_float16():
    idx = Index.load(SNAP)
    assert idx.vectors.dtype == "float16" and len(idx.vectors) == len(idx.chunks)


@needs_index
@pytest.mark.realdata
def test_recall_at_5_on_real_eval_set():
    import yaml

    from secanalyst.retrieval.embedding import FastEmbedder

    MEASURED_RECALL_AT_5 = 0.767  # `pipeline eval`, filters ticker+fy, bge-small, 30 questions
    es = yaml.safe_load((REPO_ROOT / "data" / "eval" / "retrieval_eval.yaml").read_text())
    try:
        emb = FastEmbedder()
    except Exception:  # noqa: BLE001 - model not cached and offline
        pytest.skip("embedding model unavailable")
    r = evaluate(Index.load(SNAP), es["questions"], emb, ("ticker", "fy"))
    assert r["recall_at_5"] >= MEASURED_RECALL_AT_5 - 0.05
