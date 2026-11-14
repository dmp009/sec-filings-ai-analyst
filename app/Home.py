"""SEC filings analyst: landing page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app.common import footer, get_as_of, get_companies, setup

setup("Home")
st.title("SEC filings analyst")
st.markdown(
    "An analyst tool over the 10-K and 10-Q filings and XBRL financial data of eight large "
    "S&P 500 companies: " + ", ".join(c.ticker for c in get_companies()) + ". "
    "Ratios are computed deterministically from XBRL; text answers are retrieved from the "
    "filings and cite their source passages."
)
st.markdown(f"**Data as of {get_as_of()}.** Sources: SEC EDGAR filings and company-facts XBRL.")

st.subheader("Who it is for")
p1, p2, p3 = st.columns(3)
p1.markdown(
    "**Equity research analyst**\n\nFind what a company says about a topic, with the passage and "
    "filing, and see what changed in its risk factors since last year."
)
p2.markdown(
    "**Credit & due-diligence analyst**\n\nSee red flags in one view, with comparable leverage, "
    "liquidity and cash-conversion ratios and their definitions."
)
p3.markdown(
    "**Client-facing banker**\n\nPrepare a meeting with a one-page Client brief: key metrics "
    "against peers, top risks and recent changes, each with a citation."
)

st.subheader("Views")
v1, v2 = st.columns(2)
with v1:
    st.markdown(
        "**Benchmarking**. Fifteen ratios, five fiscal years, latest-year "
        "ranking against the peer median, source tag and accession for every value."
    )
    st.page_link("pages/3_Benchmarking.py", label="Open Benchmarking")
    st.markdown(
        "**Ask the filings**. Plain-English questions answered with quoted "
        "passages and key sentences, each cited to filing, year and item."
    )
    st.page_link("pages/1_Ask_the_filings.py", label="Open Ask the filings")
    st.markdown(
        "**Data quality**. Checks run over the filings and financials, and "
        "what they found."
    )
    st.page_link("pages/5_Data_quality.py", label="Open Data quality")
with v2:
    st.markdown(
        "**Due diligence**. What changed in each company's risk factors "
        "between its latest two 10-Ks, a red-flag radar and customer concentration."
    )
    st.page_link("pages/2_Due_diligence.py", label="Open Due diligence")
    st.markdown(
        "**Client brief**. A one-page PDF per company: metrics against the "
        "peer median, top risks with citations, what changed and red flags."
    )
    st.page_link("pages/4_Client_brief.py", label="Open Client brief")
st.markdown("The About page in the sidebar explains what the tool does, how, and its limits.")

footer()
