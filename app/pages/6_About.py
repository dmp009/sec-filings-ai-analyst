"""About: what the tool is, how it works, sources and limitations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.common import footer, get_as_of, setup

setup("About")
st.title("About")
st.subheader("What it is")
st.markdown(
    "A portfolio project: an analyst tool over the SEC filings and XBRL data of eight large "
    "S&P 500 companies (AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, TSLA)."
)
st.subheader("How it works")
st.markdown(
    "- Filings and XBRL company facts are downloaded from SEC EDGAR, split into items and "
    "stored in a DuckDB warehouse, committed as a parquet snapshot.\n"
    "- Financial ratios are computed deterministically from XBRL tags, never imputed: a missing "
    "input gives n/a, a meaningless result gives n/m, each with a reason.\n"
    "- The app reads the committed snapshot only; it needs no network and no API key to browse."
)
st.subheader("Sources")
st.markdown(
    f"SEC EDGAR 10-K and 10-Q filings and the company-facts XBRL API. Data as of {get_as_of()}."
)
st.subheader("Limitations")
st.markdown(
    "- Eight companies only, last five fiscal years.\n"
    "- Fiscal years are not calendar-aligned (NVIDIA ends in January, Microsoft in June, Apple "
    "in September, Broadcom around the start of November).\n"
    "- Some definitions follow documented rulings (for example ROIC is n/m when invested "
    "capital is under 10% of total assets); see the tooltips on the Benchmarking page.\n"
    "- Not investment advice."
)
st.subheader("Links")
st.markdown("- Source code: https://github.com/dmp009/sec-filings-ai-analyst\n"
    "- Author: https://github.com/dmp009")
footer()
