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
    st.set_page_config(page_title=f"SEC filings analyst - {title}", page_icon=":material/description:", layout="wide")


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
    st.space("medium")
    st.caption(get_settings().disclaimer)
    st.caption(f"Data as of {get_as_of()} (committed snapshot; no live data).")


@st.cache_resource(show_spinner="Loading search index...")
def get_index():
    from secanalyst.retrieval.search import Index

    return Index.load(ROOT / "data" / "snapshot")


@st.cache_resource(show_spinner="Loading embedding model...")
def get_embedder():
    """The bge-small model, or None when it cannot load (offline first run): the Ask page then
    falls back to keyword (BM25) search with a visible note."""
    try:
        from secanalyst.retrieval.embedding import FastEmbedder

        return FastEmbedder()
    except Exception:  # noqa: BLE001 - any load failure means "use the BM25 fallback"
        return None


@st.cache_data
def get_risk_diff():
    import pandas as pd

    return pd.read_parquet(ROOT / "data" / "snapshot" / "risk_diff.parquet")


@st.cache_data
def get_radar():
    import pandas as pd

    return pd.read_parquet(ROOT / "data" / "snapshot" / "radar.parquet")


@st.cache_data
def get_chunks():
    """Passage text and metadata only (no vectors): the diligence page needs no embedding."""
    import pandas as pd

    return pd.read_parquet(ROOT / "data" / "snapshot" / "chunks.parquet")


@st.cache_data
def get_customer_concentration():
    import pandas as pd

    from secanalyst.diligence.redflags import customer_concentration

    rows = customer_concentration(get_chunks())
    return pd.DataFrame(rows, columns=["ticker", "fy", "percent", "citation"])


@st.cache_resource(show_spinner=False)
def get_index_chunks():
    """An Index over the passages only (no vectors), enough for the PDF brief."""
    from secanalyst.retrieval.search import Index

    return Index.load(ROOT / "data" / "snapshot", with_vectors=False)
