"""Data quality report produced by the pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.common import ROOT, footer, setup

setup("Data quality")
st.title("Data quality")
report = ROOT / "data_quality_report.md"
if report.exists():
    st.markdown(report.read_text(encoding="utf-8"))
else:
    st.info(
        "No data quality report has been generated yet (run `python -m secanalyst.pipeline ingest`)."
    )
footer()
