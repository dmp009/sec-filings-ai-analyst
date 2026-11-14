import pandas as pd

from secanalyst.config import load_red_flags, load_settings
from secanalyst.diligence.redflags import customer_concentration, radar
from secanalyst.diligence.riskdiff import diff_filings, diff_risks, split_risks
from secanalyst.retrieval.embedding import FakeEmbedder

R_CYBER = (
    "Cyber attacks and data breaches could disrupt our operations and expose customer data. "
    "We have experienced ransomware attempts and unauthorized access to our systems in the past."
)
R_CHINA = (
    "Tariffs and trade tensions between the United States and China may reduce demand for our "
    "products and raise the cost of components built in Taiwan and mainland China sites."
)
R_FX = (
    "Fluctuations in foreign currency exchange rates could reduce our reported revenue and "
    "operating margins because a large share of our sales are made outside the United States."
)
R_NEW = (
    "Our use of generative artificial intelligence models exposes us to intellectual property "
    "claims, regulatory scrutiny and reputational harm if outputs are inaccurate or biased."
)


def _body(heading, para):
    return f"{heading}\n{para} {para}\n"


def _1a(*pairs):
    return (
        "Item 1A. Risk Factors\nThe following risks could harm our business."
        + "\n"
        + "".join(_body(h, p) for h, p in pairs)
    )


def test_split_risks_headings_and_bodies():
    text = _1a(
        ("Cyber attacks could disrupt our business.", R_CYBER),
        ("Trade tensions with China could hurt results.", R_CHINA),
    )
    risks = split_risks(text)
    assert [r.title for r in risks] == [
        "Cyber attacks could disrupt our business.",
        "Trade tensions with China could hurt results.",
    ]
    assert "ransomware" in risks[0].text


def test_split_risks_ignores_bullet_summary_and_empty():
    text = "Item 1A\nSummary\n•Failure to meet needs may adversely impact results.\n"
    assert split_risks(text) == []
    assert split_risks("") == []


def _risks(*pairs):
    return split_risks(_1a(*pairs))


def test_diff_statuses_exact():
    st = load_settings()
    prev = _risks(
        ("Cyber attacks could disrupt our business.", R_CYBER),
        ("Trade tensions with China could hurt results.", R_CHINA),
        ("Currency swings could reduce our reported revenue.", R_FX),
    )
    curr = _risks(
        ("Cyber attacks could disrupt our business.", R_CYBER),  # identical
        (
            "Trade tensions with China could hurt results.",
            R_CHINA + " New export licence rules also apply to advanced chips shipped to China.",
        ),  # reworded
        ("Generative AI creates new legal exposure for us.", R_NEW),  # added; FX removed
    )
    # the hashing FakeEmbedder is far less compressed than bge, so it needs a lower match bar
    out = diff_risks(prev, curr, FakeEmbedder(), 0.7, st.risk_change, st.risk_lexical)
    by = {c.status: c for c in out}
    assert sorted(c.status for c in out) == ["changed", "new", "removed", "unchanged"]
    assert by["unchanged"].similarity > 0.999
    assert by["removed"].prev.title.startswith("Currency")
    assert by["removed"].curr is None
    assert by["new"].curr.title.startswith("Generative") and by["new"].prev is None
    assert by["changed"].prev is not None and by["changed"].curr is not None


def test_thresholds_come_from_config():
    st = load_settings()
    assert 0.5 < st.risk_match < st.risk_change <= 1.0


def test_diff_filings_excludes_missing_1a_with_note():
    secs = pd.DataFrame(
        [
            {"filing_id": "a1", "ticker": "AAA", "form": "10-K", "fiscal_year": "2024",
             "item": "1A", "text": _1a(("Cyber attacks could disrupt our business.", R_CYBER))},
            {"filing_id": "a2", "ticker": "AAA", "form": "10-K", "fiscal_year": "2025",
             "item": "1A", "text": _1a(("Cyber attacks could disrupt our business.", R_CYBER))},
            {"filing_id": "b1", "ticker": "BBB", "form": "10-K", "fiscal_year": "2025",
             "item": "1A", "text": _1a(("Cyber attacks could disrupt our business.", R_CYBER))},
        ]
    )  # fmt: skip
    rows, notes = diff_filings(secs, FakeEmbedder(), 0.8, 0.95)
    assert set(rows["ticker"]) == {"AAA"}
    assert (rows["fy_prev"] == "2024").all() and (rows["fy_curr"] == "2025").all()
    assert any("BBB" in n for n in notes)


def _chunks(rows):
    return pd.DataFrame(
        [
            {"chunk_id": f"{t}-10-K-{fy}-{it}-{i:04d}", "filing_id": "x", "ticker": t,
             "form": "10-K", "fiscal_year": fy, "item": it, "position": 0, "text": txt,
             "n_words": len(txt.split()), "period_end": "2025-12-31"}
            for i, (t, fy, it, txt) in enumerate(rows)
        ]
    )  # fmt: skip


def test_radar_counts():
    ch = _chunks(
        [
            ("AAA", "2025", "1A", "We suffered a data breach and a ransomware incident."),
            ("AAA", "2025", "1A", "Cybersecurity risks are significant for our systems."),
            ("AAA", "2025", "1A", "Nothing relevant here at all."),
            ("AAA", "2025", "3", "A class action lawsuit was filed against us."),
        ]
    )
    r = radar(ch, load_red_flags())
    cy = r[(r.ticker == "AAA") & (r.category == "cybersecurity")].iloc[0]
    assert cy.hits == 2 and len(cy.chunk_ids) == 2 and cy.fy == "2025"
    lit = r[r.category == "litigation"].iloc[0]
    assert lit.hits == 1
    assert "going_concern" not in set(r.category)  # zero-hit categories are omitted


def test_customer_concentration_parsed_with_citation():
    ch = _chunks(
        [
            (
                "AAA",
                "2025",
                "1A",
                "In fiscal 2025, one customer accounted for 12% of revenue. Other text.",
            )
        ]
    )
    out = customer_concentration(ch)
    assert len(out) == 1
    t, fy, pct, cit = out[0]
    assert (t, fy, pct) == ("AAA", "2025", 12.0)
    assert cit.startswith("AAA · 10-K FY2025") and "Item 1A" in cit


def test_customer_concentration_ignores_aggregates():
    ch = _chunks(
        [
            ("AAA", "2025", "1", "Sales to distributors accounted for 57% of our net revenue."),
            (
                "AAA",
                "2025",
                "1",
                "Our top five end customers accounted for 35% of our net revenue.",
            ),
        ]
    )
    assert customer_concentration(ch) == []


def test_customer_concentration_multiple_and_prior_year():
    ch = _chunks(
        [
            ("N", "2026", "1A", "For fiscal year 2026, sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14% of total revenue."),
            ("N", "2026", "7", "For fiscal year 2025, sales to one direct customer represented 12% of total revenue."),
            ("N", "2025", "1A", "Sales to direct Customers A, B and C represented 12%, 11% and 11% of total revenue, respectively."),
        ]
    )  # fmt: skip
    got = sorted((fy, p) for _, fy, p, _ in customer_concentration(ch))
    assert got == [("2025", 11.0), ("2025", 12.0), ("2026", 14.0), ("2026", 22.0)]
