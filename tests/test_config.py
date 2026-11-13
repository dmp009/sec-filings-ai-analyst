from datetime import date

from secanalyst import config

EXPECTED = {
    "AAPL": ("0000320193", 9),
    "MSFT": ("0000789019", 6),
    "NVDA": ("0001045810", 1),
    "AMZN": ("0001018724", 12),
    "GOOGL": ("0001652044", 12),
    "META": ("0001326801", 12),
    "AVGO": ("0001730168", 10),
    "TSLA": ("0001318605", 12),
}

CONCEPTS = [
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "depreciation_amortization",
    "operating_cash_flow",
    "capex",
    "sbc",
    "total_assets",
    "total_equity",
    "total_debt",
    "cash_short_term_investments",
    "receivables",
    "inventory",
    "payables",
    "income_tax",
    "pretax_income",
    "short_term_borrowings",
    "commercial_paper",
    "debt_current",
    "debt_noncurrent",
    "finance_lease_liability_current",
    "finance_lease_liability_noncurrent",
    "cash_and_equivalents",
    "short_term_investments",
    "marketable_securities_noncurrent",
]


def test_companies():
    cos = config.load_companies()
    assert {c.ticker: (c.cik, c.fy_end_month) for c in cos} == EXPECTED
    assert all(isinstance(c.cik, str) and len(c.cik) == 10 for c in cos)
    assert {c.ticker: c.name for c in cos}["AMZN"] == "Amazon.com, Inc."


def test_red_flag_categories():
    rf = config.load_red_flags()
    assert set(rf) == {
        "customer_concentration",
        "litigation",
        "material_weakness",
        "going_concern",
        "china_geopolitics",
        "ai_regulation",
        "export_controls",
        "cybersecurity",
    }
    for v in rf.values():
        assert v["keywords"] and 2 <= len(v["seeds"]) <= 3


def test_xbrl_tags():
    tags = config.load_xbrl_tags()
    for c in CONCEPTS:
        assert len(tags[c]) >= 1
    assert tags["revenue"][0] == "Revenues"


def test_settings():
    s = config.load_settings()
    assert s.disclaimer == "Educational project — not investment advice. Source: SEC EDGAR."
    assert s.user_agent_default == "sec-filings-ai-analyst research project"
    assert s.llm_model == "claude-sonnet-5-5"
    assert "@" not in s.user_agent_default
    assert (s.chunk_words, s.chunk_overlap, s.top_k, s.daily_llm_cap) == (320, 60, 8, 50)
    assert 0 < s.score_floor < 1
    assert s.as_of is None or isinstance(s.as_of, date)


def test_questions_and_paths():
    qs = config.load_questions()
    assert len(qs) >= 10
    assert all({"id", "ticker", "question"} <= set(q) for q in qs)
    assert config.REPO_ROOT.joinpath("config", "companies.yaml").exists()
