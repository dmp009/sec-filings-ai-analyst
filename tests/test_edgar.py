import json
from datetime import date
from pathlib import Path

import pytest

from secanalyst.ingest import edgar
from secanalyst.ingest.edgar import EdgarClient, FilingRef, RateLimiter, select_filings

FIX = Path(__file__).parent / "fixtures"


def subs():
    return json.loads((FIX / "submissions_AAPL.json").read_text())


def test_select_three_10k_plus_latest_10q_after_10k():
    refs = select_filings(subs(), date(2026, 11, 13))
    ks = [r for r in refs if r.form == "10-K"]
    qs = [r for r in refs if r.form == "10-Q"]
    assert [r.filing_date for r in ks] == [date(2025, 10, 31), date(2024, 11, 1), date(2023, 11, 3)]
    assert len(qs) == 1 and qs[0].filing_date == date(2026, 8, 1)
    assert all(r.form in ("10-K", "10-Q") for r in refs)  # 10-K/A and 8-K ignored
    r = ks[0]
    assert r.ticker == "AAPL" and r.cik == "0000320193" and r.period_end == date(2025, 9, 27)
    assert r.primary_doc_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        f"{r.accession.replace('-', '')}/aapl-20251031.htm"
    )


def test_as_of_cutoff_excludes_later_filings():
    refs = select_filings(subs(), date(2025, 1, 1))
    assert [r.filing_date for r in refs if r.form == "10-K"] == [
        date(2024, 11, 1),
        date(2023, 11, 3),
        date(2022, 10, 28),
    ]
    assert not [r for r in refs if r.form == "10-Q" and r.filing_date <= date(2024, 11, 1)]


def test_no_10q_after_latest_10k_gives_none():
    s = subs()
    rec = s["filings"]["recent"]
    keep = [
        i for i, f in enumerate(rec["form"]) if f != "10-Q" or rec["filingDate"][i] < "2025-10-31"
    ]
    s["filings"]["recent"] = {k: [v[i] for i in keep] for k, v in rec.items()}
    assert [r for r in select_filings(s, date(2026, 11, 13)) if r.form == "10-Q"] == []


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.calls = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_rate_limiter_never_exceeds_8_per_second():
    c = FakeClock()
    rl = RateLimiter(8, clock=c.now, sleep=c.sleep)
    stamps = []
    for _ in range(20):
        rl.wait()
        stamps.append(c.now())
    for s in stamps:
        assert sum(1 for x in stamps if s <= x < s + 1.0) <= 8


def test_user_agent_env_verbatim(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Foo foo@bar.com")
    assert edgar.resolve_user_agent() == "Foo foo@bar.com"


def test_user_agent_default_plus_env_contact(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("SEC_CONTACT", "me@x.com")
    ua = edgar.resolve_user_agent(env_file=tmp_path / ".env")
    assert ua == "sec-filings-ai-analyst research project me@x.com"


def test_user_agent_contact_from_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    f = tmp_path / ".env"
    f.write_text("# c\nOTHER=1\nSEC_CONTACT='file@x.com'\n")
    assert edgar.resolve_user_agent(env_file=f).endswith(" file@x.com")


def test_user_agent_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    with pytest.raises(RuntimeError, match="Set SEC_CONTACT in .env"):
        edgar.resolve_user_agent(env_file=tmp_path / "nope")


class Resp:
    def __init__(self, status, body=b"{}"):
        self.status_code = status
        self.content = body
        self.text = body.decode()

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.urls = []

    def get(self, url, timeout=None):
        assert timeout == 30
        self.urls.append(url)
        return self.responses.pop(0)


def make_client(responses):
    c = FakeClock()
    sess = FakeSession(responses)
    cl = EdgarClient("UA test", session=sess, clock=c.now, sleep=c.sleep)
    return cl, sess


def test_client_sets_user_agent_and_retries(tmp_path):
    cl, sess = make_client([Resp(429), Resp(503), Resp(200, b'{"a": 1}')])
    out = tmp_path / "raw" / "x.json"
    assert cl.get_json("https://data.sec.gov/x", save=out) == {"a": 1}
    assert sess.headers["User-Agent"] == "UA test"
    assert len(sess.urls) == 3 and out.read_bytes() == b'{"a": 1}'


def test_client_gives_up_after_3_retries():
    cl, sess = make_client([Resp(500)] * 5)
    with pytest.raises(RuntimeError):
        cl.get_text("https://x")
    assert len(sess.urls) == 4


def test_fetch_submissions_follows_older_files():
    s = subs()
    older = {k: [] for k in s["filings"]["recent"]}
    older["form"] = ["10-K"]
    older["accessionNumber"] = ["0000320193-20-000001"]
    older["filingDate"] = ["2020-10-30"]
    older["reportDate"] = ["2020-09-26"]
    older["primaryDocument"] = ["old.htm"]
    s["filings"]["recent"] = {k: v[:8] for k, v in s["filings"]["recent"].items()}  # only 2 10-K
    s["filings"]["files"] = [{"name": "CIK0000320193-submissions-001.json"}]
    cl, sess = make_client([Resp(200, json.dumps(older).encode())])
    merged = edgar.fetch_submissions(cl, "0000320193", date(2026, 11, 13), first=s)
    assert sess.urls == ["https://data.sec.gov/submissions/CIK0000320193-submissions-001.json"]
    ks = [r for r in select_filings(merged, date(2026, 11, 13)) if r.form == "10-K"]
    assert len(ks) == 3 and ks[-1].filing_date == date(2020, 10, 30)


def test_company_facts_url():
    cl, sess = make_client([Resp(200)])
    edgar.fetch_company_facts(cl, "0000320193")
    assert sess.urls == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"]


def test_filingref_is_dataclass():
    assert FilingRef.__dataclass_fields__.keys() >= {"ticker", "primary_doc_url"}
