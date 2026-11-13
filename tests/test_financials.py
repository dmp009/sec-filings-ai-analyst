"""XBRL annual extraction and ratios (design §6.3, §9.2, §9.4)."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from secanalyst.config import REPO_ROOT, load_companies, load_xbrl_tags
from secanalyst.financials.facts import FINANCIAL_COLUMNS, extract_annual
from secanalyst.financials.ratios import RATIO_COLUMNS, RATIOS, compute_ratios

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- helpers


def fin(values: dict[str, float], ticker="X", fy="2025", pe=date(2025, 12, 31), prior=None):
    """Long-format fact_financials rows for one (or two, with ``prior``) fiscal years."""
    rows = [
        {"ticker": ticker, "fiscal_year_label": fy, "period_end": pe, "concept": c, "value": v,
         "tag": c, "accession": "acc"}
        for c, v in values.items()
    ]  # fmt: skip
    if prior:
        pfy, ppe = str(int(fy) - 1), date(pe.year - 1, pe.month, pe.day)
        rows += [
            {"ticker": ticker, "fiscal_year_label": pfy, "period_end": ppe, "concept": c,
             "value": v, "tag": c, "accession": "acc0"}
            for c, v in prior.items()
        ]  # fmt: skip
    return pd.DataFrame(rows, columns=FINANCIAL_COLUMNS)


def ratio(df: pd.DataFrame, name: str, fy="2025") -> pd.Series:
    r = df[(df.ratio == name) & (df.fiscal_year_label == fy)]
    assert len(r) == 1, f"{name}: {len(r)} rows"
    return r.iloc[0]


FULL = {
    "revenue": 100.0, "cost_of_revenue": 40.0, "operating_income": 50.0, "net_income": 25.0,
    "operating_cash_flow": 30.0, "capex": 10.0, "income_tax": 50.0, "pretax_income": 100.0,
    "total_equity": 100.0, "total_debt": 50.0, "liquidity": 30.0, "receivables": 20.0,
    "inventory": 8.0, "payables": 12.0, "depreciation_amortization": 10.0,
    "total_assets": 500.0,
}  # fmt: skip


# ---------------------------------------------------------------- ratios: hand values


def test_gross_margin():
    assert ratio(compute_ratios(fin(FULL)), "gross_margin").value == pytest.approx(0.60)


def test_fcf_margin_and_conversion():
    r = compute_ratios(fin(FULL))
    assert ratio(r, "fcf_margin").value == pytest.approx(0.20)  # FCF 30 - 10 = 20
    assert ratio(r, "fcf_conversion").value == pytest.approx(0.80)  # 20 / 25
    assert ratio(r, "capex_intensity").value == pytest.approx(0.10)


def test_nopat_clamps_tax_rate_and_roic():
    r = compute_ratios(fin(FULL))
    # tax 50 / pretax 100 = 50 % -> clamped 35 % -> NOPAT 50 * 0.65 = 32.5
    # invested capital = 100 + 50 - 30 = 120
    roic = ratio(r, "roic")
    assert roic.status == "ok"
    assert roic.value == pytest.approx(32.5 / 120)
    assert round(roic.value, 6) == 0.270833


def test_negative_equity_is_not_meaningful():
    r = compute_ratios(fin({**FULL, "total_equity": -5.0}))
    for name in ("roe", "roic"):
        row = ratio(r, name)
        assert row.status == "n/m"
        assert pd.isna(row.value)
        assert "equity" in row.reason and "-5" in row.reason


def test_roic_not_meaningful_when_invested_capital_is_small_vs_assets():
    # equity 10 + debt 50 - liquidity 55 = 5 < 10 % of assets 100
    r = compute_ratios(
        fin({**FULL, "total_equity": 10.0, "liquidity": 55.0, "total_assets": 100.0})
    )
    row = ratio(r, "roic")
    assert row.status == "n/m" and pd.isna(row.value)
    assert row.reason == (
        "invested capital $0.0bn < 10% of total assets ($0.0bn); ROIC dominated by cash netting"
    )
    assert ratio(r, "roe").status == "ok"


def test_roic_needs_total_assets():
    r = compute_ratios(fin({k: v for k, v in FULL.items() if k != "total_assets"}))
    assert ratio(r, "roic").reason == "missing concept total_assets"


def test_debt_to_ebitda_na_without_d_and_a():
    r = compute_ratios(fin({k: v for k, v in FULL.items() if k != "depreciation_amortization"}))
    assert ratio(r, "debt_to_ebitda").reason == "missing concept depreciation_amortization"


def test_non_positive_invested_capital_is_not_meaningful():
    r = compute_ratios(fin({**FULL, "total_equity": 10.0, "liquidity": 100.0}))
    row = ratio(r, "roic")
    assert row.status == "n/m" and "invested capital" in row.reason
    assert ratio(r, "roe").status == "ok"


def test_days_ratios_use_365_and_year_end_balances():
    r = compute_ratios(fin(FULL))
    assert ratio(r, "dso").value == pytest.approx(73.0)  # 20 / 100 * 365
    assert ratio(r, "dio").value == pytest.approx(8 / 40 * 365)
    assert ratio(r, "dpo").value == pytest.approx(12 / 40 * 365)
    assert ratio(r, "ccc").value == pytest.approx(73.0 + 73.0 - 109.5)


def test_other_ratios():
    r = compute_ratios(fin(FULL, prior={**FULL, "revenue": 80.0}))
    assert ratio(r, "revenue_growth").value == pytest.approx(0.25)
    assert ratio(r, "operating_margin").value == pytest.approx(0.50)
    assert ratio(r, "net_margin").value == pytest.approx(0.25)
    assert ratio(r, "roe").value == pytest.approx(0.25)
    assert ratio(r, "net_cash").value == pytest.approx(-20.0)
    assert ratio(r, "debt_to_ebitda").value == pytest.approx(50 / 60)
    first = ratio(r, "revenue_growth", fy="2024")
    assert first.status == "n/a" and first.reason.startswith("missing concept revenue")


def test_missing_capex_makes_fcf_ratios_na_with_reason():
    values = {k: v for k, v in FULL.items() if k != "capex"}
    r = compute_ratios(fin(values))
    for name in ("fcf_margin", "fcf_conversion", "capex_intensity"):
        row = ratio(r, name)
        assert row.status == "n/a"
        assert row.reason == "missing concept capex"
        assert pd.isna(row.value)
    assert ratio(r, "gross_margin").status == "ok"


def test_gross_margin_falls_back_to_gross_profit_tag():
    values = {k: v for k, v in FULL.items() if k != "cost_of_revenue"} | {"gross_profit": 55.0}
    r = compute_ratios(fin(values))
    assert ratio(r, "gross_margin").value == pytest.approx(0.55)
    assert ratio(r, "dio").value == pytest.approx(8 / 45 * 365)  # cost = revenue - GP


def test_missing_inventory_makes_dio_and_ccc_na():
    r = compute_ratios(fin({k: v for k, v in FULL.items() if k != "inventory"}))
    assert ratio(r, "dio").reason == "missing concept inventory"
    assert ratio(r, "ccc").status == "n/a"


def test_every_ratio_row_has_a_status_and_reason_when_not_ok():
    r = compute_ratios(fin({"revenue": 100.0}))
    assert list(r.columns) == RATIO_COLUMNS
    assert set(r.ratio) == set(RATIOS)
    assert set(r.status) <= {"ok", "n/a", "n/m"}
    bad = r[r.status != "ok"]
    assert bad.reason.notna().all() and (bad.reason.str.len() > 0).all()


# ---------------------------------------------------------------- extraction


def _fact(val, end, start=None, form="10-K", filed=None, accn=None):
    f = {"end": end, "val": val, "form": form, "filed": filed or f"{end[:4]}-02-01",
         "accn": accn or f"acc-{(filed or end)[:4]}", "fy": int(end[:4]), "fp": "FY"}  # fmt: skip
    if start:
        f["start"] = start
    return f


def _year(y: int, val, **kw):
    """Annual duration fact for calendar fiscal year y."""
    return _fact(val, f"{y}-12-31", start=f"{y}-01-01", filed=f"{y + 1}-02-01", **kw)


def _facts(gaap: dict[str, list[dict]]) -> dict:
    return {"facts": {"us-gaap": {t: {"units": {"USD": xs}} for t, xs in gaap.items()}}}


def _filings(ticker="X", years=(2025, 2024, 2023)):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "form": "10-K",
                "accession": f"acc-{y + 1}",
                "period_end": date(y, 12, 31),
                "fiscal_year_label": str(y),
            }
            for y in years
        ]
    )


TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "total_equity": ["StockholdersEquity"],
    "short_term_borrowings": ["ShortTermBorrowings"],
    "commercial_paper": ["CommercialPaper"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent"],
    "debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "finance_lease_liability_current": ["FinanceLeaseLiabilityCurrent"],
    "finance_lease_liability_noncurrent": ["FinanceLeaseLiabilityNoncurrent"],
    "finance_lease_liability_total": ["FinanceLeaseLiability"],
    "total_debt": ["DebtLongtermAndShorttermCombinedAmount"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "short_term_investments": ["MarketableSecuritiesCurrent"],
    "marketable_securities_noncurrent": ["MarketableSecuritiesNoncurrent"],
    "cash_short_term_investments": ["CashCashEquivalentsAndShortTermInvestments"],
    "marketable_securities_total": ["AvailableForSaleSecuritiesDebtSecurities"],
    "cash_equivalents": ["CashEquivalentsAtCarryingValue"],
    "depreciation_amortization": ["DepreciationDepletionAndAmortization"],
    "depreciation": ["Depreciation"],
    "amortization_intangibles": ["AmortizationOfIntangibleAssets"],
}


def value(df, concept, fy):
    r = df[(df.concept == concept) & (df.fiscal_year_label == fy)]
    assert len(r) == 1, f"{concept} FY{fy}: {len(r)} rows"
    return r.iloc[0]


def test_revenue_tag_switch_across_years_resolved_by_fallback_order():
    # FY2021-2022 only the ASC 606 tag; FY2023-2025 both tags (Revenues preferred)
    gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            _year(y, 1000 + y) for y in range(2021, 2026)
        ],
        "Revenues": [_year(y, 2000 + y) for y in range(2023, 2026)],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings())
    assert list(df.columns) == FINANCIAL_COLUMNS
    rev = df[df.concept == "revenue"].set_index("fiscal_year_label")
    assert sorted(rev.index) == ["2021", "2022", "2023", "2024", "2025"]
    assert rev.loc["2025", "tag"] == "Revenues" and rev.loc["2025", "value"] == 4025
    assert rev.loc["2022", "tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert rev.loc["2021", "value"] == 3021
    assert rev.loc["2021", "period_end"] == date(2021, 12, 31)


def test_quarterly_10q_and_wrong_durations_are_ignored_and_latest_filed_wins():
    gaap = {
        "Revenues": [
            _year(2025, 500, accn="orig"),
            _fact(510, "2025-12-31", start="2025-01-01", filed="2027-02-01", accn="restated"),
            _fact(130, "2025-12-31", start="2025-10-01"),  # quarter in a 10-K
            _fact(999, "2025-12-31", start="2025-01-01", form="10-Q"),
            _fact(777, "2025-12-31", start="2023-01-01"),  # 3-year cumulative
        ]
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    r = value(df, "revenue", "2025")
    assert (r.value, r.accession) == (510, "restated")


def test_balance_concepts_use_instants_and_52_week_prior_years():
    # 52/53-week year: prior period ends drift by a few days and are matched within 7 days
    ends = {"2025": "2025-09-27", "2024": "2024-09-28", "2023": "2023-09-30",
            "2022": "2022-09-24", "2021": "2021-09-25"}  # fmt: skip
    gaap = {
        "Revenues": [_fact(100 + int(y), e, start=f"{int(y) - 1}-09-28") for y, e in ends.items()],
        "StockholdersEquity": [_fact(10 + int(y), e) for y, e in ends.items()],
    }
    filings = pd.DataFrame(
        [{"ticker": "A", "form": "10-K", "accession": f"a{y}",
          "period_end": date.fromisoformat(ends[y]), "fiscal_year_label": y}
         for y in ("2025", "2024", "2023")]
    )  # fmt: skip
    df = extract_annual(_facts(gaap), TAGS, filings)
    eq = df[df.concept == "total_equity"].set_index("fiscal_year_label")
    assert eq.loc["2021", "value"] == 2031
    assert eq.loc["2022", "period_end"] == date(2022, 9, 24)
    assert (df.ticker == "A").all()


def test_total_debt_sums_components_and_records_them():
    gaap = {
        "CommercialPaper": [_fact(5, "2025-12-31")],
        "LongTermDebtCurrent": [_fact(10, "2025-12-31")],
        "LongTermDebtNoncurrent": [_fact(80, "2025-12-31")],
        "FinanceLeaseLiabilityNoncurrent": [_fact(3, "2025-12-31")],
        "DebtLongtermAndShorttermCombinedAmount": [_fact(999, "2025-12-31")],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    d = value(df, "total_debt", "2025")
    assert d.value == 98
    assert d.tag.startswith("sum:") and "CommercialPaper" in d.tag
    assert "LongTermDebtNoncurrent" in d.tag and "FinanceLeaseLiabilityNoncurrent" in d.tag


def test_total_debt_uses_lumped_tag_only_without_components():
    gaap = {"DebtLongtermAndShorttermCombinedAmount": [_fact(70, "2025-12-31")]}
    d = value(extract_annual(_facts(gaap), TAGS, _filings(years=(2025,))), "total_debt", "2025")
    assert (d.value, d.tag) == (70, "fallback:DebtLongtermAndShorttermCombinedAmount")


def test_long_term_debt_total_minus_current_avoids_double_counting():
    gaap = {
        "LongTermDebt": [_fact(100, "2025-12-31")],  # total, includes the current portion
        "LongTermDebtCurrent": [_fact(15, "2025-12-31")],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    assert value(df, "debt_noncurrent", "2025").value == 85
    assert value(df, "debt_noncurrent", "2025").tag == "LongTermDebt-LongTermDebtCurrent"
    assert value(df, "total_debt", "2025").value == 100


def test_liquidity_components_missing_count_as_zero_when_cash_present():
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": [_fact(30, "2025-12-31")],
        "MarketableSecuritiesCurrent": [_fact(20, "2025-12-31")],
    }
    d = value(extract_annual(_facts(gaap), TAGS, _filings(years=(2025,))), "liquidity", "2025")
    assert d.value == 50
    assert d.tag == "sum:CashAndCashEquivalentsAtCarryingValue+MarketableSecuritiesCurrent"


def test_liquidity_uses_total_securities_only_when_no_split_is_tagged():
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": [_fact(10, "2025-12-31"), _fact(9, "2024-12-31")],
        "AvailableForSaleSecuritiesDebtSecurities": [
            _fact(40, "2025-12-31"),
            _fact(35, "2024-12-31"),
        ],
        "CashEquivalentsAtCarryingValue": [_fact(8, "2025-12-31")],
        "MarketableSecuritiesCurrent": [_fact(30, "2024-12-31")],
        "Revenues": [_year(2025, 1), _year(2024, 1)],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    # AFS debt securities include the cash equivalents already in cash: 10 + (40 - 8)
    liq = value(df, "liquidity", "2025")
    assert liq.value == 42
    assert liq.tag == (
        "sum:CashAndCashEquivalentsAtCarryingValue+"
        "(AvailableForSaleSecuritiesDebtSecurities-CashEquivalentsAtCarryingValue)"
    )
    assert value(df, "liquidity", "2024").value == 39  # split tagged: total not added


def test_total_securities_overlap_floors_at_zero_and_needs_cash_equivalents():
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": [_fact(10, "2025-12-31"), _fact(9, "2024-12-31")],
        "AvailableForSaleSecuritiesDebtSecurities": [
            _fact(5, "2025-12-31"),
            _fact(35, "2024-12-31"),
        ],
        "CashEquivalentsAtCarryingValue": [_fact(8, "2025-12-31")],
        "Revenues": [_year(2025, 1), _year(2024, 1)],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    assert value(df, "liquidity", "2025").value == 10  # max(5 - 8, 0) = 0
    # no cash-equivalents tag -> overlap unknown -> total securities not added
    assert value(df, "liquidity", "2024").value == 9


def test_liquidity_absent_without_cash():
    gaap = {"MarketableSecuritiesCurrent": [_fact(20, "2025-12-31")]}
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    assert df[df.concept == "liquidity"].empty


def test_finance_lease_total_is_debt_only_without_split_components():
    gaap = {
        "LongTermDebtNoncurrent": [_fact(40, "2025-12-31"), _fact(30, "2024-12-31")],
        "FinanceLeaseLiability": [_fact(60, "2025-12-31"), _fact(20, "2024-12-31")],
        "FinanceLeaseLiabilityCurrent": [_fact(2, "2024-12-31")],
        "Revenues": [_year(2025, 1), _year(2024, 1)],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    d25 = value(df, "total_debt", "2025")
    assert d25.value == 100 and "FinanceLeaseLiability" in d25.tag
    d24 = value(df, "total_debt", "2024")  # split component tagged: total not added
    assert d24.value == 32 and d24.tag.endswith("FinanceLeaseLiabilityCurrent")


def test_finance_lease_total_not_added_to_debt_that_includes_leases():
    tags = {**TAGS, "debt_noncurrent": ["LongTermDebtAndCapitalLeaseObligations"]}
    gaap = {
        "LongTermDebtAndCapitalLeaseObligations": [_fact(50, "2025-12-31")],
        "FinanceLeaseLiability": [_fact(4, "2025-12-31")],
    }
    df = extract_annual(_facts(gaap), tags, _filings(years=(2025,)))
    assert value(df, "total_debt", "2025").value == 50


def test_depreciation_only_d_and_a_withheld_when_amortization_is_material_elsewhere():
    # FY2024 reports material amortization; FY2025 only depreciation -> no D&A for FY2025
    gaap = {
        "Depreciation": [_year(2025, 5), _year(2024, 5)],
        "AmortizationOfIntangibleAssets": [_year(2024, 30)],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    assert df[(df.concept == "depreciation_amortization") & (df.fiscal_year_label == "2025")].empty
    assert value(df, "depreciation_amortization", "2024").value == 35
    # immaterial amortization elsewhere (< 10 % of D&A) keeps the depreciation-only value
    gaap["AmortizationOfIntangibleAssets"] = [_year(2024, 0.1)]
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    d25 = value(df, "depreciation_amortization", "2025")
    assert (d25.value, d25.tag) == (5, "sum:Depreciation")


def test_d_and_a_falls_back_to_depreciation_plus_amortization():
    gaap = {
        "Depreciation": [_year(2025, 40)],
        "AmortizationOfIntangibleAssets": [_year(2025, 5)],
        "DepreciationDepletionAndAmortization": [_year(2024, 33)],
        "Revenues": [_year(2024, 1)],
    }
    df = extract_annual(_facts(gaap), TAGS, _filings(years=(2025,)))
    d25 = value(df, "depreciation_amortization", "2025")
    assert (d25.value, d25.tag) == (45, "sum:Depreciation+AmortizationOfIntangibleAssets")
    d24 = value(df, "depreciation_amortization", "2024")
    assert (d24.value, d24.tag) == (33, "DepreciationDepletionAndAmortization")


def test_extract_trimmed_apple_fixture():
    facts = json.loads((FIX / "companyfacts_AAPL_trim.json").read_text())
    filings = pd.DataFrame(
        [{"ticker": "AAPL", "form": "10-K", "accession": a, "period_end": date.fromisoformat(p),
          "fiscal_year_label": p[:4]}
         for a, p in [("0000320193-26-000026", "2026-09-26"),
                      ("0000320193-25-000079", "2025-09-27"),
                      ("0000320193-24-000123", "2024-09-28")]]
    )  # fmt: skip
    df = extract_annual(facts, load_xbrl_tags(), filings)
    rev = value(df, "revenue", "2026")
    assert rev.value == 478_834_000_000 and rev.accession == "0000320193-26-000026"
    assert rev.period_end == date(2026, 9, 26)
    assert sorted(df[df.concept == "revenue"].fiscal_year_label) == [
        "2022", "2023", "2024", "2025", "2026"
    ]  # fmt: skip
    assert value(df, "total_assets", "2026").value == 404_548_000_000
    assert not df.duplicated(["ticker", "fiscal_year_label", "concept"]).any()


# ---------------------------------------------------------------- real-data acceptance

MANIFEST = REPO_ROOT / "data" / "raw" / "manifest.json"


@pytest.mark.realdata
@pytest.mark.skipif(not MANIFEST.exists(), reason="data/raw not downloaded")
def test_real_company_facts(capsys):
    from secanalyst.pipeline import filings_frame

    m = json.loads(MANIFEST.read_text())
    tags = load_xbrl_tags()
    fins, filings = [], filings_frame(m)
    for c in load_companies():
        facts = json.loads((REPO_ROOT / m["companies"][c.ticker]["company_facts"]).read_text())
        fins.append(extract_annual(facts, tags, filings[filings.ticker == c.ticker]))
    df = pd.concat(fins, ignore_index=True)
    ratios = compute_ratios(df)

    rev = df[df.concept == "revenue"]
    years = rev.groupby("ticker").fiscal_year_label.nunique()
    assert len(years) == 8 and (years == 5).all(), years

    nv = rev[rev.ticker == "NVDA"].sort_values("period_end").iloc[-1]
    assert nv.fiscal_year_label == "2026"
    assert (nv.period_end.year, nv.period_end.month) == (2026, 1)

    # back-test of the AFS-minus-cash-equivalents liquidity path (used for NVDA FY2026) on
    # FY2025, where NVIDIA still tags current marketable securities separately
    n25 = df[(df.ticker == "NVDA") & (df.fiscal_year_label == "2025")].set_index("concept").value
    afs_path = (
        n25["cash_and_equivalents"] + n25["marketable_securities_total"] - n25["cash_equivalents"]
    )
    assert afs_path == pytest.approx(n25["liquidity"], rel=0.01)

    assert set(ratios.status) <= {"ok", "n/a", "n/m"}
    bad = ratios[ratios.status != "ok"]
    assert bad.reason.notna().all() and (bad.reason.str.len() > 0).all()

    # Apple: ROE/ROIC status follows the rule (n/m only for equity <= 0 or IC <= 0)
    aapl = ratios[(ratios.ticker == "AAPL") & ratios.ratio.isin(["roe", "roic"])]
    eq = df[(df.ticker == "AAPL") & (df.concept == "total_equity")].set_index("fiscal_year_label")
    for r in aapl.itertuples():
        if eq.loc[r.fiscal_year_label, "value"] <= 0:
            assert r.status == "n/m"
        elif r.ratio == "roe":
            assert r.status == "ok"
    with capsys.disabled():
        print()
        for r in aapl.sort_values(["ratio", "fiscal_year_label"]).itertuples():
            print(f"AAPL FY{r.fiscal_year_label} {r.ratio}: {r.status} {r.value} {r.reason}")
