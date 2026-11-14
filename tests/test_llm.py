"""Optional LLM layer: verification, cache, daily cap, pipeline `ai` (fake clients only)."""

import json

from secanalyst import pipeline
from secanalyst.answer import llm
from secanalyst.answer.llm import DraftAnswer, answer_cached
from secanalyst.answer.verify import verify_answer
from secanalyst.retrieval.search import Hit


def hit(cid, text):
    return Hit(cid, 0.1, "NVDA", "10-K", "2026", "1A", text, "2026-01-25")


HITS = [
    hit("c1", "Revenue was $1.2 billion in fiscal 2026, up 15% from the prior year."),
    hit("c2", "Export controls restrict sales to China."),
]


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def write_answer(self, prompt):
        self.calls += 1
        return self.responses[min(self.calls - 1, len(self.responses) - 1)]


GOOD = {"answer": "Revenue was 1.2 billion, up 15%.", "citations": ["c1"]}


def test_verify_ok_and_normalised_numbers():
    assert verify_answer(DraftAnswer(GOOD["answer"], ["c1"]), HITS) == []
    assert verify_answer(DraftAnswer("It was $1.2 billion in 2026.", ["c1"]), HITS) == []


def test_verify_rejects_uncited_foreign_and_bad_numbers():
    assert verify_answer(DraftAnswer("Export controls apply.", []), HITS)
    assert verify_answer(DraftAnswer("Export controls apply.", ["zzz"]), HITS)
    assert verify_answer(DraftAnswer("Revenue was 1.2 billion.", ["c2"]), HITS)  # number not in c2
    assert verify_answer(DraftAnswer("Revenue grew 40%.", ["c1"]), HITS)


def kw(tmp_path, **extra):
    return dict(cache_dir=tmp_path / "cache", usage_path=tmp_path / "u.json", cap=50, **extra)


def test_cache_hit_avoids_second_call(tmp_path):
    c = FakeClient(GOOD)
    a = answer_cached("q?", HITS, c, **kw(tmp_path))
    assert a and a.citations == ["c1"] and c.calls == 1
    c2 = FakeClient(GOOD)
    assert answer_cached("q?", HITS, c2, **kw(tmp_path)).answer == GOOD["answer"]
    assert c2.calls == 0
    assert answer_cached("q?", HITS, c2, refresh=True, **kw(tmp_path)) and c2.calls == 1


def test_cached_only_without_client_and_unverified_never_cached(tmp_path):
    assert answer_cached("q?", HITS, None, **kw(tmp_path)) is None
    bad = FakeClient({"answer": "Revenue grew 40%.", "citations": ["c1"]})
    assert answer_cached("q?", HITS, bad, **kw(tmp_path)) is None
    assert bad.calls == 2  # one retry, then unverified -> None
    assert not list((tmp_path / "cache").glob("*.json"))


def test_retry_recovers(tmp_path):
    c = FakeClient({"answer": "x 99", "citations": ["c1"]}, GOOD)
    assert answer_cached("q?", HITS, c, **kw(tmp_path)) is not None and c.calls == 2


def test_daily_cap_blocks_next_call(tmp_path):
    k = kw(tmp_path)
    k["cap"] = 3
    c = FakeClient(GOOD)
    for i in range(3):
        assert answer_cached(f"q{i}", HITS, c, **k)
    assert answer_cached("q3", HITS, c, **k) is None
    assert c.calls == 3
    assert json.loads((tmp_path / "u.json").read_text())["count"] == 3


def test_prompt_marks_passages_untrusted():
    p = llm.build_prompt("q?", HITS)
    assert "<passages>" in p and "c1" in p and "ignore" in p.lower()


def test_ai_without_key_exits_zero(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pipeline.main(["ai"])
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


def test_verify_unit_aware():
    h = [hit("c1", "Sales rose 12 percent to $11.2 billion in 2026.")]
    ok = lambda t: verify_answer(DraftAnswer(t, ["c1"]), h) == []
    assert ok("Sales were $11.2 billion.") and ok("Up 12%.") and ok("In 2026.")
    assert not ok("Sales were $12 million.")
    assert not ok("Sales were $11.2 million.")
    assert not ok("Sales were $12 billion.")
    assert not ok("Up 11.2%.")


def test_usage_fails_closed_and_atomic(tmp_path):
    u = tmp_path / "u.json"
    u.write_text("{broken")
    c = FakeClient(GOOD)
    assert answer_cached("q", HITS, c, **{**kw(tmp_path), "usage_path": u}) is None
    assert c.calls == 0
    u.unlink()
    assert answer_cached("q", HITS, c, **{**kw(tmp_path), "usage_path": u})
    assert not list(tmp_path.glob("*.tmp"))


def test_verify_sign_aware():
    def ok(chunk, t):
        return verify_answer(DraftAnswer(t, ["c1"]), [hit("c1", chunk)]) == []

    assert not ok("Sales grew 12 percent.", "Sales fell -12%.")
    assert not ok("Sales grew 12 percent.", "Sales fell \u221212%.")
    assert ok("Sales grew 12 percent.", "Sales grew 12%.")
    assert ok("Net loss of $(12).", "A loss of -12.")
    assert ok("Margin fell -3 percent.", "Margin fell -3%.") and ok("Down -3%.", "Down 3%.")
    assert ok("From 2024-2026 sales grew.", "In 2026.")
    assert not ok("Sales were 12 million.", "Sales were -12 million.")


def test_verify_leading_minus():
    chunk = "Revenue grew 12 percent to $11.2 billion in fiscal 2026. Headcount was 1,200."
    for t in ["-12%", "\n\u221212%", "(-12%)", "x\n-12%"]:
        assert verify_answer(DraftAnswer(t, ["c1"]), [hit("c1", chunk)]), t
    assert verify_answer(DraftAnswer("12%", ["c1"]), [hit("c1", chunk)]) == []
    assert verify_answer(DraftAnswer("2024-2026", ["c1"]), [hit("c1", "2024-2026")]) == []
