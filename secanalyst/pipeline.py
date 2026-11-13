"""Pipeline CLI: `python -m secanalyst.pipeline ingest`."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime

from secanalyst.config import REPO_ROOT, load_companies, load_settings
from secanalyst.ingest import edgar

RAW = REPO_ROOT / "data" / "raw"


def ingest(client: edgar.EdgarClient | None = None, as_of: date | None = None) -> dict:
    """Download submissions, selected primary documents and company facts; write manifest."""
    client = client or edgar.EdgarClient(edgar.resolve_user_agent())
    as_of = as_of or load_settings().as_of or date.today()
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest: dict = {"as_of": as_of.isoformat(), "fetched_at": ts, "companies": {}}
    for c in load_companies():
        p_sub = edgar.raw_path("submissions", c.ticker, f"CIK{c.cik}.json", ts, RAW)
        subs = edgar.fetch_submissions(client, c.cik, as_of, save=p_sub)
        refs = edgar.select_filings(subs, as_of, c.ticker)
        docs = []
        for r in refs:
            name = f"{r.form}_{r.accession}_{r.primary_doc_url.rsplit('/', 1)[-1]}"
            p = edgar.raw_path("filings", c.ticker, name, ts, RAW)
            client.get_text(r.primary_doc_url, save=p)
            docs.append({**asdict(r), "path": str(p.relative_to(REPO_ROOT))})
        p_facts = edgar.raw_path("companyfacts", c.ticker, f"CIK{c.cik}.json", ts, RAW)
        edgar.fetch_company_facts(client, c.cik, save=p_facts)
        manifest["companies"][c.ticker] = {
            "submissions": str(p_sub.relative_to(REPO_ROOT)),
            "filings": docs,
            "company_facts": str(p_facts.relative_to(REPO_ROOT)),
        }
        print(f"{c.ticker}: {len(docs)} filings")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "manifest.json").write_text(
        json.dumps(manifest, indent=1, default=str), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="secanalyst.pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="download EDGAR raw data for all companies")
    args = ap.parse_args(argv)
    if args.cmd == "ingest":
        ingest()


if __name__ == "__main__":
    main()
