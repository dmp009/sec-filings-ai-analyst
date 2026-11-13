"""Shared helpers for the Streamlit pages. Reads only committed files (parquet snapshot,
config, data_quality_report.md); no network and no API key needed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # config paths are relative to the repo root

import streamlit as st

from secanalyst.config import load_companies, load_settings
from secanalyst.warehouse.snapshot import load_snapshot


def setup(title: str) -> None:
    st.set_page_config(page_title=f"SEC filings analyst - {title}", page_icon=None, layout="wide")


@st.cache_resource(show_spinner="Loading data snapshot...")
def get_con():
    return load_snapshot()


@st.cache_data
def get_as_of() -> str:
    row = get_con().execute("SELECT value FROM meta WHERE key = 'as_of'").fetchone()
    return row[0] if row else "unknown"


@st.cache_data
def get_companies() -> list:
    return load_companies()


@st.cache_data
def get_settings():
    return load_settings()


@st.cache_data
def get_ratios():
    return get_con().execute("SELECT * FROM fact_ratios").df()


@st.cache_data
def get_financials():
    return get_con().execute("SELECT * FROM fact_financials").df()


def footer() -> None:
    st.divider()
    st.caption(get_settings().disclaimer)
    st.caption(f"Data as of {get_as_of()} (committed snapshot; no live data).")
