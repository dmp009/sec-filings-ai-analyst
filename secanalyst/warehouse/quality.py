"""Data-quality checks over the warehouse (design §6.2, §6.3). Failures are reported, never
silently passed; the report is committed as ``data_quality_report.md``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from secanalyst.financials.ratios import RATIOS
from secanalyst.parse.sections import expected_fiscal_year
from secanalyst.warehouse.store import TABLES

N_YEARS = 5
MIN_CHARS = {"1A": 5_000, "7": 5_000}  # Items 1A / 7 shorter than this are suspicious
MAX_CHARS = 1_000_000  # any section longer than this swallowed its neighbours
CORE_CONCEPTS = [
    "revenue", "operating_income", "net_income", "operating_cash_flow", "capex",
    "total_equity", "total_debt", "liquidity", "income_tax", "pretax_income",
    "depreciation_amortization", "receivables", "inventory", "payables",
]  # fmt: skip
CHECKS = (
    ("tenk_missing_item", "error", "10-K whose Item 1A or Item 7 is missing or empty"),
    ("filing_without_sections", "error", "filing with no section rows"),
    ("tenq_missing_mdna", "warning", "10-Q without Part I Item 2 (MD&A)"),
    (
        "section_length",
        "warning",
        (
            f"Item 1A or 7 shorter than {MIN_CHARS['1A']:,} chars, or a section longer than "
            f"{MAX_CHARS:,} chars"
        ),
    ),
    ("duplicate_section", "error", "the same text in two items of one filing"),
    (
        "fiscal_label_mismatch",
        "error",
        (
            "fiscal-year label differs from the fiscal year containing the period end "
            "(10-K: also the period-end year)"
        ),
    ),
    ("financials_years", "error", f"company with fewer than {N_YEARS} fiscal years of revenue"),
    (
        "missing_concept",
        "warning",
        "core concept missing in a company-year (ratios using it are n/a, never imputed)",
    ),
    (
        "ratio_schema",
        "error",
        (
            "fact_ratios row breaking the schema: known ratio, status in ok / n/a / n/m, "
            "value iff ok, reason when not ok"
        ),
    ),
    ("financials_schema", "error", "fact_financials row with empty tag or accession"),
    (
        "debt_without_finance_leases",
        "warning",
        "total debt has no finance-lease component although FinanceLeaseLiability is reported",
    ),
)
KEY_RATIOS = [
    ("revenue_growth", "Rev. growth", "pct"),
    ("gross_margin", "Gross margin", "pct"),
    ("operating_margin", "Op. margin", "pct"),
    ("fcf_margin", "FCF margin", "pct"),
    ("fcf_conversion", "FCF conv.", "pct"),
    ("roic", "ROIC", "pct"),
    ("roe", "ROE", "pct"),
    ("net_cash", "Net cash ($bn)", "bn"),
    ("debt_to_ebitda", "Debt/EBITDA", "x"),
    ("ccc", "CCC (days)", "days"),
]


@dataclass
class QualityIssue:
    check: str
    ticker: str | None
    detail: str
    severity: Literal["error", "warning"]


def _filing_name(r) -> str:
    return f"{r.ticker} {r.form} {r.filing_id} (FY{r.fiscal_year_label}, {r.period_end})"


def _section_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    filings = con.execute("SELECT * FROM fact_filings ORDER BY ticker, period_end").df()
    sections = con.execute("SELECT filing_id, item, text, n_chars FROM fact_sections").df()
    by_filing = {k: g for k, g in sections.groupby("filing_id")}
    for f in filings.itertuples():
        name = _filing_name(f)
        g = by_filing.get(f.filing_id)
        if g is None:
            issues.append(QualityIssue("filing_without_sections", f.ticker, name, "error"))
            continue
        present = {r.item: r.n_chars for r in g.itertuples() if r.n_chars > 0}
        if f.form == "10-K":
            for item in ("1A", "7"):
                if item not in present:
                    issues.append(
                        QualityIssue(
                            "tenk_missing_item", f.ticker, f"{name}: Item {item} missing", "error"
                        )
                    )
                elif present[item] < MIN_CHARS[item]:
                    issues.append(
                        QualityIssue(
                            "section_length",
                            f.ticker,
                            f"{name}: Item {item} only {present[item]:,} chars",
                            "warning",
                        )
                    )
        elif "P1-2" not in present:
            issues.append(
                QualityIssue("tenq_missing_mdna", f.ticker, f"{name}: Part I Item 2 missing",
                             "warning")
            )  # fmt: skip
        for r in g[g["n_chars"] > MAX_CHARS].itertuples():
            issues.append(
                QualityIssue(
                    "section_length", f.ticker, f"{name}: Item {r.item} {r.n_chars:,} chars",
                    "warning",
                )
            )  # fmt: skip
        dup = g[g.duplicated("text", keep=False)]
        if not dup.empty:
            issues.append(
                QualityIssue(
                    "duplicate_section",
                    f.ticker,
                    f"{name}: identical text in items {', '.join(sorted(dup['item']))}",
                    "error",
                )
            )
    return issues


def _label_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    issues = []
    rows = con.execute(
        "SELECT f.*, c.fy_end_month FROM fact_filings f JOIN dim_company c USING (ticker) "
        "ORDER BY ticker, period_end"
    ).df()
    for r in rows.itertuples():
        pe = pd.Timestamp(r.period_end).date()
        expected = expected_fiscal_year(pe, int(r.fy_end_month))
        label = int(r.fiscal_year_label)
        if label != expected or (r.form == "10-K" and label != pe.year):
            issues.append(
                QualityIssue(
                    "fiscal_label_mismatch",
                    r.ticker,
                    f"{_filing_name(r)}: expected FY{expected}",
                    "error",
                )
            )
    return issues


def _financial_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    issues = []
    fin = con.execute("SELECT * FROM fact_financials").df()
    tickers = [r[0] for r in con.execute("SELECT ticker FROM dim_company ORDER BY 1").fetchall()]
    years = fin[fin["concept"] == "revenue"].groupby("ticker")["fiscal_year_label"].nunique()
    for t in tickers:
        n = int(years.get(t, 0))
        if n < N_YEARS:
            issues.append(
                QualityIssue("financials_years", t, f"{n} fiscal year(s) of revenue", "error")
            )
        g = fin[fin["ticker"] == t]
        all_years = sorted(g["fiscal_year_label"].unique())
        for concept in CORE_CONCEPTS:
            have = set(g.loc[g["concept"] == concept, "fiscal_year_label"])
            missing = [y for y in all_years if y not in have]
            if missing:
                issues.append(
                    QualityIssue(
                        "missing_concept",
                        t,
                        f"{concept} missing for FY{', FY'.join(missing)}",
                        "warning",
                    )
                )
    debt = fin[fin["concept"] == "total_debt"].set_index(["ticker", "fiscal_year_label"])
    leases = fin[fin["concept"] == "finance_lease_liability_total"]
    for r in leases.itertuples():
        key = (r.ticker, r.fiscal_year_label)
        if (
            key in debt.index
            and "FinanceLease" not in debt.loc[key, "tag"]
            and ("LongTermDebtAndCapitalLeaseObligations" not in debt.loc[key, "tag"])
        ):
            issues.append(
                QualityIssue(
                    "debt_without_finance_leases",
                    r.ticker,
                    f"FY{r.fiscal_year_label}: total debt {debt.loc[key, 'tag']} omits "
                    f"FinanceLeaseLiability ({r.value / 1e9:,.1f} $bn)",
                    "warning",
                )
            )
    bad = fin[(fin["tag"].fillna("") == "") | (fin["accession"].fillna("") == "")]
    for r in bad.itertuples():
        issues.append(
            QualityIssue(
                "financials_schema",
                r.ticker,
                f"FY{r.fiscal_year_label} {r.concept}: empty tag or accession",
                "error",
            )
        )
    return issues


RATIO_SCHEMA = pa.DataFrameSchema(
    {
        "ticker": pa.Column(str),
        "fiscal_year_label": pa.Column(str),
        "ratio": pa.Column(str, pa.Check.isin(RATIOS)),
        "status": pa.Column(str, pa.Check.isin(["ok", "n/a", "n/m"])),
        "value": pa.Column(float, nullable=True),
        "reason": pa.Column(nullable=True),  # str or null; content checked below
    },
    checks=[
        pa.Check(
            lambda df: (df["status"] == "ok") == df["value"].notna(),
            name="value present iff status ok",
        ),
        pa.Check(
            lambda df: (
                (df["status"] == "ok")
                | (df["reason"].notna() & (df["reason"].astype(str).str.len() > 0))
            ),
            name="reason when not ok",
        ),
    ],
)


def _ratio_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    ratios = con.execute("SELECT * FROM fact_ratios").df()
    if ratios.empty:
        return []
    ratios["value"] = ratios["value"].astype(float)
    try:
        RATIO_SCHEMA.validate(ratios, lazy=True)
        return []
    except SchemaErrors as e:
        issues = []
        for fc in e.failure_cases.itertuples():
            idx = fc.index
            if idx is not None and not pd.isna(idx) and int(idx) in ratios.index:
                r = ratios.loc[int(idx)]
                where = f"FY{r['fiscal_year_label']} {r['ratio']} (status {r['status']})"
                ticker = r["ticker"]
            else:
                where, ticker = "table", None
            issues.append(
                QualityIssue("ratio_schema", ticker, f"{where}: failed '{fc.check}'", "error")
            )
        return issues


def run_quality_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    return _section_checks(con) + _label_checks(con) + _financial_checks(con) + _ratio_checks(con)


def _fmt(value, status, kind) -> str:
    if status != "ok":
        return status
    if kind == "pct":
        return f"{100 * value:.1f}%"
    if kind == "bn":
        return f"{value / 1e9:,.1f}"
    if kind == "x":
        return f"{value:.2f}x"
    return f"{value:.0f}"


def key_ratio_table(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Markdown table of key ratios for each company's latest fiscal year."""
    df = con.execute(
        "SELECT r.* FROM fact_ratios r JOIN (SELECT ticker, max(fiscal_year_label) AS fy "
        "FROM fact_ratios GROUP BY ticker) l ON r.ticker = l.ticker AND r.fiscal_year_label = l.fy"
    ).df()
    head = ["Ticker", "FY", "Period end"] + [label for _, label, _ in KEY_RATIOS]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for ticker, g in df.groupby("ticker", sort=True):
        by = g.set_index("ratio")
        cells = [
            ticker,
            g["fiscal_year_label"].iloc[0],
            str(pd.Timestamp(g["period_end"].iloc[0]).date()),
        ]
        for name, _, kind in KEY_RATIOS:
            cells.append(_fmt(by.loc[name, "value"], by.loc[name, "status"], kind))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def write_quality_report(
    issues: list[QualityIssue],
    path: Path | str = "data_quality_report.md",
    con: duckdb.DuckDBPyConnection | None = None,
) -> None:
    """Markdown report: issues, checks run and, given ``con``, row counts, key ratios and the
    list of n/a / n/m ratio reasons."""
    lines = ["# Data quality report", ""]
    if con is not None:
        as_of = con.execute("SELECT value FROM meta WHERE key = 'as_of'").fetchone()
        if as_of:
            lines += [f"Data as of {as_of[0]} (SEC EDGAR).", ""]
    if not issues:
        lines.append("No issues found.")
    else:
        errors = sum(i.severity == "error" for i in issues)
        lines += [f"{errors} error(s), {len(issues) - errors} warning(s).", ""]
        lines += ["| Severity | Check | Ticker | Detail |", "|---|---|---|---|"]
        for i in sorted(issues, key=lambda x: (x.severity != "error", x.check, x.ticker or "")):
            detail = i.detail.replace("|", "\\|")
            lines.append(f"| {i.severity} | {i.check} | {i.ticker or '-'} | {detail} |")
    lines += ["", "## Checks run", "", "| Check | Severity | What it detects |", "|---|---|---|"]
    lines += [f"| `{c}` | {sev} | {what} |" for c, sev, what in CHECKS]
    if con is not None:
        lines += ["", "## Row counts", "", "| Table | Rows |", "|---|---|"]
        for table in TABLES:
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            lines.append(f"| {table} | {n} |")
        if con.execute("SELECT count(*) FROM fact_ratios").fetchone()[0]:
            lines += [
                "",
                "## Key ratios, latest fiscal year",
                "",
                (
                    "Fiscal years differ (Apple ends in September, Microsoft in June, NVIDIA in "
                    "January, Broadcom in October/November): compare by fiscal-year label and "
                    "check the period end. `n/a` = input concept missing, `n/m` = not meaningful."
                ),
                "",
                *key_ratio_table(con),
                "",
                "## Ratios not computed",
                "",
                "| Ratio | Status | Reason | Company-years |",
                "|---|---|---|---|",
            ]
            rows = con.execute(
                "SELECT ratio, status, reason, string_agg(ticker || ' FY' || fiscal_year_label, "
                "', ' ORDER BY ticker, fiscal_year_label) FROM fact_ratios WHERE status <> 'ok' "
                "GROUP BY ALL ORDER BY ratio, status, reason"
            ).fetchall()
            for ratio, status, reason, where in rows:
                lines.append(f"| {ratio} | {status} | {reason} | {where} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
