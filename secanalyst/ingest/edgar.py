"""EDGAR client (rate limited, retrying) and filing selection. Parsing lives elsewhere."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from secanalyst.config import REPO_ROOT, load_settings

SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
TIMEOUT = 30
MAX_RETRIES = 3
N_10K = 3


def _read_env_file(path: Path, key: str) -> str | None:
    """Tiny .env parser: KEY=value lines, '#' comments, optional quotes."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip("'\"") or None
    return None


def resolve_user_agent(env_file: Path | None = None) -> str:
    """SEC_USER_AGENT verbatim, else '<default> <SEC_CONTACT>' (env or .env), else error."""
    ua = os.environ.get("SEC_USER_AGENT")
    if ua:
        return ua
    contact = os.environ.get("SEC_CONTACT") or _read_env_file(
        env_file or REPO_ROOT / ".env", "SEC_CONTACT"
    )
    if not contact:
        raise RuntimeError("Set SEC_CONTACT in .env — the SEC requires a contact in the User-Agent")
    return f"{load_settings().user_agent_default} {contact}"


class RateLimiter:
    """Minimum spacing of 1/max_rps between calls (so never more than max_rps per second)."""

    def __init__(self, max_rps: float = 8, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / max_rps
        self._clock, self._sleep = clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            delay = self._last + self.interval - now
            if delay > 0:
                self._sleep(delay)
                now = self._clock()
        self._last = now


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        max_rps: float = 8,
        session=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._limiter = RateLimiter(max_rps, clock, sleep)
        self._sleep = sleep

    def _get(self, url: str, save: Path | None):
        for attempt in range(MAX_RETRIES + 1):
            self._limiter.wait()
            resp = self.session.get(url, timeout=TIMEOUT)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                self._sleep(2.0**attempt)
                continue
            resp.raise_for_status()
            break
        if save is not None:
            save.parent.mkdir(parents=True, exist_ok=True)
            save.write_bytes(resp.content)
        return resp

    def get_json(self, url: str, save: Path | None = None) -> dict:
        return self._get(url, save).json()

    def get_text(self, url: str, save: Path | None = None) -> str:
        return self._get(url, save).text


def raw_path(kind: str, ticker: str, name: str, ts: str, root: Path | None = None) -> Path:
    """data/raw/<kind>/<UTC ts>_<ticker>_<name>"""
    return (root or REPO_ROOT / "data" / "raw") / kind / f"{ts}_{ticker}_{name}"


@dataclass(frozen=True)
class FilingRef:
    ticker: str
    cik: str
    form: str
    accession: str
    filing_date: date
    period_end: date | None
    primary_doc_url: str


def _d(s: str) -> date | None:
    return date.fromisoformat(s) if s else None


def _rows(block: dict):
    n = len(block.get("accessionNumber", []))
    for i in range(n):
        yield {k: v[i] for k, v in block.items() if isinstance(v, list) and len(v) == n}


def select_filings(submissions: dict, as_of: date, ticker: str | None = None) -> list[FilingRef]:
    """Last 3 10-K filed <= as_of, plus the latest 10-Q filed after the latest 10-K (if any).
    Amendments (10-K/A, 10-Q/A) are ignored."""
    cik = str(submissions["cik"]).zfill(10)
    tk = ticker or (submissions.get("tickers") or [""])[0]
    rows = [
        r
        for r in _rows(submissions["filings"]["recent"])
        if r["form"] in ("10-K", "10-Q") and _d(r["filingDate"]) <= as_of
    ]
    rows.sort(key=lambda r: r["filingDate"], reverse=True)

    def ref(r: dict) -> FilingRef:
        url = DOC_URL.format(
            cik=int(cik), acc=r["accessionNumber"].replace("-", ""), doc=r["primaryDocument"]
        )
        return FilingRef(
            tk,
            cik,
            r["form"],
            r["accessionNumber"],
            _d(r["filingDate"]),
            _d(r.get("reportDate", "")),
            url,
        )

    ks = [r for r in rows if r["form"] == "10-K"][:N_10K]
    out = [ref(r) for r in ks]
    if ks:
        qs = [r for r in rows if r["form"] == "10-Q" and r["filingDate"] > ks[0]["filingDate"]]
        if qs:
            out.append(ref(qs[0]))
    return out


def fetch_submissions(
    client: EdgarClient, cik: str, as_of: date, first: dict | None = None, save: Path | None = None
) -> dict:
    """Submissions JSON; if recent has < 3 usable 10-Ks, merge older `filings.files` pages."""
    subs = first or client.get_json(SUBMISSIONS_URL.format(name=f"CIK{cik}.json"), save=save)
    recent = subs["filings"]["recent"]

    def n_10k() -> int:
        return sum(1 for r in _rows(recent) if r["form"] == "10-K" and _d(r["filingDate"]) <= as_of)

    for f in subs["filings"].get("files", []):
        if n_10k() >= N_10K:
            break
        older = client.get_json(SUBMISSIONS_URL.format(name=f["name"]))
        for k, v in older.items():
            recent.setdefault(k, []).extend(v)
    return subs


def fetch_company_facts(client: EdgarClient, cik: str, save: Path | None = None) -> dict:
    return client.get_json(FACTS_URL.format(cik=cik), save=save)
