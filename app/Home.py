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
    "**Equity analyst**\n\nCompare peers on margins, returns, leverage and working capital, "
    "and trace each number to its XBRL tag."
)
p2.markdown(
    "**Risk reviewer**\n\nFind and compare risk-factor and MD&A language across companies "
    "and years."
)
p3.markdown(
    "**Curious investor**\n\nAsk a question in plain English and read the answer with its "
    "supporting passages."
)

st.subheader("Views")
v1, v2 = st.columns(2)
with v1:
    st.markdown(
        "**Benchmarking** — available now. Fifteen ratios, five fiscal years, latest-year "
        "ranking against the peer median, source tag and accession for every value."
    )
    st.page_link("pages/3_Benchmarking.py", label="Open Benchmarking")
    st.markdown(
        "**Ask the filings** — available now. Plain-English questions answered with quoted "
        "passages and key sentences, each cited to filing, year and item."
    )
    st.page_link("pages/1_Ask_the_filings.py", label="Open Ask the filings")
    st.markdown(
        "**Data quality** — available now. Checks run over the filings and financials, and "
        "what they found."
    )
    st.page_link("pages/5_Data_quality.py", label="Open Data quality")
with v2:
    st.markdown(
        "**Due diligence** — available now. What changed in each company's risk factors "
        "between its latest two 10-Ks, a red-flag radar and customer concentration."
    )
    st.page_link("pages/2_Due_diligence.py", label="Open Due diligence")
    st.markdown("**Company explorer** — coming soon.")
st.markdown("See also: " + "About (what, how, limitations) in the sidebar.")

footer()
