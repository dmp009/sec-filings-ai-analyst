"""Pipeline CLI: `python -m secanalyst.pipeline ingest|build`."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from secanalyst.config import REPO_ROOT, load_companies, load_settings, load_xbrl_tags
from secanalyst.financials.facts import extract_annual
from secanalyst.financials.ratios import compute_ratios
from secanalyst.ingest import edgar
from secanalyst.parse import sections
from secanalyst.warehouse import quality, snapshot, store

RAW = REPO_ROOT / "data" / "raw"
MANIFEST = RAW / "manifest.json"
REPORT = REPO_ROOT / "data_quality_report.md"
FILING_COLUMNS = [
    "filing_id", "ticker", "form", "accession", "filing_date", "period_end", "fiscal_year_label",
]  # fmt: skip


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


def _parse(manifest: dict, root: Path, with_sections: bool):
    filings, secs = [], []
    for ticker, entry in manifest["companies"].items():
        for f in entry["filings"]:
            html = sections.parse_html((root / f["path"]).read_bytes())
            label, pe = sections.fiscal_year_label(html), sections.period_end(html)
            filings.append(
                {"filing_id": f["accession"], "ticker": ticker, "form": f["form"],
                 "accession": f["accession"], "filing_date": date.fromisoformat(f["filing_date"]),
                 "period_end": pe, "fiscal_year_label": label}
            )  # fmt: skip
            if with_sections:
                ref = edgar.FilingRef(
                    ticker=ticker, cik=f["cik"], form=f["form"], accession=f["accession"],
                    filing_date=date.fromisoformat(f["filing_date"]), period_end=pe,
                    primary_doc_url=f["primary_doc_url"],
                )  # fmt: skip
                items = sections.split_items(sections.html_to_text(html), f["form"])
                secs.append(sections.section_rows(ref, label, items))
    fil = pd.DataFrame(filings, columns=FILING_COLUMNS)
    sec = (
        pd.concat(secs, ignore_index=True)
        if secs
        else pd.DataFrame(columns=sections.SECTION_COLUMNS)
    )
    return fil, sec


def filings_frame(manifest: dict, root: Path = REPO_ROOT) -> pd.DataFrame:
    """``fact_filings`` rows; fiscal-year label and period end come from the filing's dei."""
    return _parse(manifest, root, with_sections=False)[0]


def build(
    manifest_path: Path = MANIFEST,
    root: Path = REPO_ROOT,
    db_path: Path = store.DB_PATH,
    snapshot_dir: Path = snapshot.SNAPSHOT_DIR,
    report_path: Path = REPORT,
):
    """manifest + raw -> sections -> financials -> ratios -> warehouse -> quality report ->
    parquet snapshot. The warehouse file is rebuilt from scratch. Returns the connection."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    filings, secs = _parse(manifest, root, with_sections=True)
    companies = {c.ticker: c for c in load_companies()}
    tags = load_xbrl_tags()
    as_of = date.fromisoformat(manifest["as_of"])
    fins = []
    for ticker, entry in manifest["companies"].items():
        facts = json.loads((root / entry["company_facts"]).read_text(encoding="utf-8"))
        fins.append(extract_annual(facts, tags, filings[filings["ticker"] == ticker], as_of))
    fin = pd.concat(fins, ignore_index=True)
    ratios = compute_ratios(fin)
    dim = pd.DataFrame([companies[t].model_dump() for t in manifest["companies"]])
    meta = pd.DataFrame(
        [{"key": "as_of", "value": manifest["as_of"]},
         {"key": "fetched_at", "value": manifest.get("fetched_at", "")}]
    )  # fmt: skip

    db_path = Path(db_path)
    if str(db_path) != ":memory:" and db_path.exists():
        db_path.unlink()
    con = store.connect(db_path)
    for table, df in [("dim_company", dim), ("fact_filings", filings), ("fact_sections", secs),
                      ("fact_financials", fin), ("fact_ratios", ratios), ("meta", meta)]:  # fmt: skip
        n = store.upsert(con, table, df)
        print(f"{table}: {n} rows")
    issues = quality.run_quality_checks(con)
    quality.write_quality_report(issues, report_path, con)
    errors = sum(i.severity == "error" for i in issues)
    print(f"quality: {errors} error(s), {len(issues) - errors} warning(s) -> {report_path}")
    size = snapshot.export_snapshot(con, snapshot_dir)
    print(f"snapshot: {size / 1e6:.1f} MB -> {snapshot_dir}")
    if size > snapshot.MAX_BYTES:
        raise RuntimeError(f"snapshot {size / 1e6:.1f} MB exceeds the 60 MB budget")
    return con


def index(snapshot_dir: Path = snapshot.SNAPSHOT_DIR, embedder=None) -> int:
    """fact_sections (+ period ends) in the snapshot -> chunks.parquet + vectors.npy (float16).
    Downloads the embedding model on first use. Returns the index size in bytes."""
    from secanalyst.retrieval.embedding import FastEmbedder
    from secanalyst.retrieval.search import build_index

    snapshot_dir = Path(snapshot_dir)
    secs = pd.read_parquet(snapshot_dir / "fact_sections.parquet")
    fil = pd.read_parquet(snapshot_dir / "fact_filings.parquet")[["filing_id", "period_end"]]
    secs = secs.merge(fil, on="filing_id", how="left")
    secs["period_end"] = secs["period_end"].astype(str)
    st = load_settings()
    idx = build_index(secs, embedder or FastEmbedder(), st.chunk_words, st.chunk_overlap)
    idx.save(snapshot_dir)
    size = sum((snapshot_dir / f).stat().st_size for f in ("chunks.parquet", "vectors.npy"))
    print(f"index: {len(idx.chunks)} chunks, {size / 1e6:.1f} MB -> {snapshot_dir}")
    return size


def diligence(
    snapshot_dir: Path = snapshot.SNAPSHOT_DIR, embedder=None, reuse_diff: bool = False
) -> dict:
    """Risk-factor diffs (latest two 10-Ks per company) -> risk_diff.parquet and the red-flag
    radar over chunks.parquet -> radar.parquet. ``reuse_diff`` keeps an existing risk_diff
    (the sections did not change) so nothing is re-embedded."""
    from secanalyst.config import load_red_flags
    from secanalyst.diligence.redflags import radar
    from secanalyst.diligence.riskdiff import diff_filings

    d = Path(snapshot_dir)
    st = load_settings()
    out = d / "risk_diff.parquet"
    if reuse_diff and out.exists():
        print("risk_diff: sections unchanged, reused")
    else:
        from secanalyst.retrieval.embedding import FastEmbedder

        secs = pd.read_parquet(d / "fact_sections.parquet")
        rows, notes = diff_filings(
            secs, embedder or FastEmbedder(), st.risk_match, st.risk_change, st.risk_lexical
        )
        rows.to_parquet(out, compression="zstd", index=False)
        for n in notes:
            print("risk_diff:", n)
        print(f"risk_diff: {len(rows)} rows -> {out}")
    chunks = pd.read_parquet(d / "chunks.parquet")
    rad = radar(chunks, load_red_flags())
    rad.to_parquet(d / "radar.parquet", compression="zstd", index=False)
    print(f"radar: {len(rad)} rows -> {d / 'radar.parquet'}")
    return {"risk_diff": out, "radar": d / "radar.parquet"}


EVAL_FILTERS = ("ticker", "fy")  # what a user sets in the Ask page: company and year
EVAL_PATH = REPO_ROOT / "data" / "eval" / "retrieval_eval.yaml"


def run_eval(snapshot_dir: Path = snapshot.SNAPSHOT_DIR, embedder=None) -> dict:
    import yaml

    from secanalyst.retrieval.embedding import FastEmbedder
    from secanalyst.retrieval.search import Index, evaluate

    embedder = embedder or FastEmbedder()
    qs = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8"))["questions"]
    idx = Index.load(snapshot_dir)
    res = evaluate(idx, qs, embedder, EVAL_FILTERS)
    for p in res["per_question"]:
        print(f"  {p['id']}: rank={p['rank']} top_relevance={p['top_relevance']:.3f}")
    print(f"filters {EVAL_FILTERS}: recall@5 = {res['recall_at_5']:.3f}  MRR = {res['mrr']:.3f}"
          f"  (n={len(qs)})")  # fmt: skip
    for keys in [(), ("ticker",)]:
        r = evaluate(idx, qs, embedder, keys)
        print(f"filters {keys}: recall@5 = {r['recall_at_5']:.3f}  MRR = {r['mrr']:.3f}")
    return res


def ai(refresh: bool = False, snapshot_dir: Path = snapshot.SNAPSHOT_DIR, embedder=None) -> int:
    """Draft verified answers for config/questions.yaml (cached in data/ai_cache/). Without
    ANTHROPIC_API_KEY it only logs and returns 0. Returns the number of verified answers."""
    from secanalyst.answer import llm
    from secanalyst.config import load_questions
    from secanalyst.retrieval.search import Index, search

    if not llm.get_api_key():
        print("ai: ANTHROPIC_API_KEY is not set; skipping drafted answers (extractive only)")
        return 0
    from secanalyst.retrieval.embedding import FastEmbedder

    st = load_settings()
    embedder = embedder or FastEmbedder()
    idx = Index.load(snapshot_dir)
    client = llm.AnthropicClient()
    ok = 0
    for q in load_questions():
        filters = {"ticker": q["ticker"]} if q.get("ticker") else None
        hits = search(idx, q["question"], filters, k=st.top_k, embedder=embedder)
        d = llm.answer_cached(q["question"], hits, client, refresh=refresh)
        print(f"ai: {q['id']}: {'verified' if d else 'no verified answer'}")
        ok += d is not None
    return ok


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="secanalyst.pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="download EDGAR raw data for all companies")
    b = sub.add_parser("build", help="raw data -> warehouse, quality report and parquet snapshot")
    b.add_argument(
        "--skip-index",
        action="store_true",
        help="do not re-embed when chunks.parquet is newer than fact_sections.parquet",
    )
    sub.add_parser("index", help="chunk + embed sections into chunks.parquet and vectors.npy")
    sub.add_parser("diligence", help="risk-factor diff and red-flag radar parquet files")
    sub.add_parser("eval", help="recall@5 and MRR on data/eval/retrieval_eval.yaml")
    a = sub.add_parser("ai", help="optional verified drafted answers (needs ANTHROPIC_API_KEY)")
    a.add_argument("--refresh", action="store_true", help="ignore the cache and redraft")
    args = ap.parse_args(argv)
    if args.cmd == "ingest":
        ingest()
    elif args.cmd == "build":
        d = snapshot.SNAPSHOT_DIR
        secs_file = d / "fact_sections.parquet"
        before = secs_file.read_bytes() if secs_file.exists() else None
        build()  # rewrites every parquet, so mtimes are useless: compare the sections content
        unchanged = before == secs_file.read_bytes()
        if args.skip_index and (d / "chunks.parquet").exists() and unchanged:
            print("index: sections unchanged, skipped")
        else:
            index()
        diligence(reuse_diff=args.skip_index and unchanged)
    elif args.cmd == "index":
        index()
    elif args.cmd == "diligence":
        diligence()
    elif args.cmd == "eval":
        run_eval()
    elif args.cmd == "ai":
        ai(refresh=args.refresh)


if __name__ == "__main__":
    main()
