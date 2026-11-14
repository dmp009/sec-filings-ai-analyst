"""DuckDB warehouse, quality checks, parquet snapshot and `pipeline build`."""

import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from secanalyst.warehouse.quality import run_quality_checks, write_quality_report
from secanalyst.warehouse.snapshot import SNAPSHOT_DIR, export_snapshot, load_snapshot
from secanalyst.warehouse.store import TABLES, connect, upsert

FIX = Path(__file__).parent / "fixtures"


def _company(ticker="AAPL"):
    return pd.DataFrame([{"ticker": ticker, "name": "Apple Inc.", "cik": "0000320193",
                          "fy_end_month": 9}])  # fmt: skip


def _filing(acc="0000320193-26-000026", form="10-K", label="2026", pe=date(2026, 9, 26)):
    return pd.DataFrame([{"filing_id": acc, "ticker": "AAPL", "form": form, "accession": acc,
                          "filing_date": date(2026, 11, 3), "period_end": pe,
                          "fiscal_year_label": label}])  # fmt: skip


def _sections(acc="0000320193-26-000026", items=("1", "1A", "7"), n=30_000, form="10-K"):
    return pd.DataFrame(
        [{"filing_id": acc, "ticker": "AAPL", "form": form, "fiscal_year": "2026", "item": k,
          "title": k, "text": f"Item {k}. " + "x" * n, "n_chars": n + 9} for k in items]
    )  # fmt: skip


def _con(**kw):
    con = connect(":memory:")
    upsert(con, "dim_company", _company())
    upsert(con, "fact_filings", _filing())
    upsert(con, "fact_sections", _sections(**kw))
    return con


def test_schema_has_all_tables():
    con = connect(":memory:")
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert set(TABLES) <= have
    assert {"dim_company", "fact_filings", "fact_sections", "fact_financials", "fact_ratios",
            "fact_chunks", "fact_ai_answers", "meta"} <= have  # fmt: skip


def test_upsert_replaces_by_natural_key_and_rejects_unknown_tables():
    con = connect(":memory:")
    upsert(con, "fact_filings", _filing())
    upsert(con, "fact_filings", _filing(label="2099"))
    rows = con.execute("SELECT fiscal_year_label FROM fact_filings").fetchall()
    assert rows == [("2099",)]
    with pytest.raises(ValueError):
        upsert(con, "fact_filings; DROP TABLE meta", _filing())
    with pytest.raises(ValueError):
        upsert(con, "fact_filings", _filing().drop(columns="period_end"))


def test_fact_ratios_status_is_constrained():
    con = connect(":memory:")
    bad = pd.DataFrame([{"ticker": "X", "fiscal_year_label": "2025",
                         "period_end": date(2025, 12, 31), "ratio": "roe", "value": None,
                         "status": "bogus", "reason": None}])  # fmt: skip
    with pytest.raises(duckdb.ConstraintException):
        upsert(con, "fact_ratios", bad)


def test_quality_clean_filing_has_no_section_issues():
    issues = run_quality_checks(_con())
    assert not [i for i in issues if i.check in ("tenk_missing_item", "duplicate_section")]


@pytest.mark.parametrize("missing", ["1A", "7"])
def test_quality_10k_without_item_is_an_error_naming_the_filing(missing):
    items = tuple(k for k in ("1", "1A", "7") if k != missing)
    issues = run_quality_checks(_con(items=items))
    hits = [i for i in issues if i.check == "tenk_missing_item"]
    assert len(hits) == 1
    assert hits[0].severity == "error"
    assert "0000320193-26-000026" in hits[0].detail and f"Item {missing}" in hits[0].detail
    assert hits[0].ticker == "AAPL"


def test_quality_flags_fiscal_label_mismatch_and_bad_ratio_rows():
    con = connect(":memory:")
    upsert(con, "dim_company", _company())
    upsert(con, "fact_filings", _filing(label="2025"))
    upsert(con, "fact_sections", _sections())
    con.execute(
        "INSERT INTO fact_ratios VALUES ('AAPL', '2026', DATE '2026-09-26', 'roe', NULL, "
        "'n/a', NULL)"
    )
    checks = {i.check for i in run_quality_checks(con)}
    assert "fiscal_label_mismatch" in checks
    assert "ratio_schema" in checks


def test_quality_warns_when_debt_omits_reported_finance_leases():
    con = connect(":memory:")
    upsert(con, "dim_company", _company())
    rows = [
        ("total_debt", 40.0, "sum:LongTermDebtNoncurrent"),
        ("finance_lease_liability_total", 60.0, "FinanceLeaseLiability"),
    ]
    upsert(con, "fact_financials", pd.DataFrame(
        [{"ticker": "AAPL", "fiscal_year_label": "2026", "period_end": date(2026, 9, 26),
          "concept": c, "value": v, "tag": t, "accession": "a"} for c, v, t in rows]
    ))  # fmt: skip
    hits = [i for i in run_quality_checks(con) if i.check == "debt_without_finance_leases"]
    assert len(hits) == 1 and hits[0].severity == "warning" and "FY2026" in hits[0].detail


def test_quality_report_lists_issues(tmp_path):
    con = _con(items=("1", "7"))
    issues = run_quality_checks(con)
    out = tmp_path / "report.md"
    write_quality_report(issues, out, con)
    text = out.read_text()
    assert text.startswith("# Data quality report")
    assert "tenk_missing_item" in text and "0000320193-26-000026" in text
    assert "| fact_sections | 2 |" in text


def test_snapshot_roundtrip(tmp_path):
    con = _con()
    upsert(con, "meta", pd.DataFrame([{"key": "as_of", "value": "2026-11-13"}]))
    export_snapshot(con, tmp_path)
    assert {p.stem for p in tmp_path.glob("*.parquet")} == set(TABLES)
    snap = load_snapshot(tmp_path)
    assert snap.execute("SELECT value FROM meta WHERE key = 'as_of'").fetchone() == ("2026-11-13",)
    assert snap.execute("SELECT count(*) FROM fact_sections").fetchone()[0] == 3


@pytest.mark.skipif(not (SNAPSHOT_DIR / "meta.parquet").exists(), reason="no snapshot yet")
def test_committed_snapshot_is_within_size_budget():
    total = sum(p.stat().st_size for p in SNAPSHOT_DIR.iterdir() if p.is_file())
    assert total <= 60 * 1024 * 1024, f"snapshot is {total / 1e6:.1f} MB"
    con = load_snapshot()
    assert con.execute("SELECT value FROM meta WHERE key = 'as_of'").fetchone()[0]


def test_pipeline_build_from_a_tiny_manifest(tmp_path):
    from secanalyst import pipeline

    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(FIX / "sections" / "aapl_10k_2026_trim.htm", raw / "aapl.htm")
    shutil.copy(FIX / "companyfacts_AAPL_trim.json", raw / "facts.json")
    manifest = {
        "as_of": "2026-11-13",
        "fetched_at": "20261113T213542Z",
        "companies": {
            "AAPL": {
                "filings": [{
                    "ticker": "AAPL", "cik": "0000320193", "form": "10-K",
                    "accession": "0000320193-26-000026", "filing_date": "2026-11-03",
                    "period_end": "2026-09-26", "primary_doc_url": "u", "path": "raw/aapl.htm",
                }],
                "company_facts": "raw/facts.json",
            }
        },
    }  # fmt: skip
    (raw / "manifest.json").write_text(json.dumps(manifest))
    snap, report = tmp_path / "snapshot", tmp_path / "report.md"
    con = pipeline.build(
        manifest_path=raw / "manifest.json",
        root=tmp_path,
        db_path=tmp_path / "w.duckdb",
        snapshot_dir=snap,
        report_path=report,
    )
    assert con.execute("SELECT count(*) FROM fact_sections").fetchone()[0] == 10
    fy = con.execute(
        "SELECT DISTINCT fiscal_year_label FROM fact_financials WHERE concept = 'revenue' "
        "ORDER BY 1"
    ).fetchall()
    assert [r[0] for r in fy] == ["2022", "2023", "2024", "2025", "2026"]
    s = load_snapshot(snap)
    assert s.execute("SELECT value FROM meta WHERE key = 'as_of'").fetchone()[0] == "2026-11-13"
    assert s.execute("SELECT count(*) FROM fact_ratios").fetchone()[0] > 0
    assert "# Data quality report" in report.read_text()


def test_quality_report_explains_empty_fact_chunks(tmp_path):
    con = _con(items=("1", "7"))
    out = tmp_path / "report.md"
    write_quality_report(run_quality_checks(con), out, con)
    assert "| fact_chunks | 0 (declared, empty; passages are stored in chunks.parquet" in out.read_text()
