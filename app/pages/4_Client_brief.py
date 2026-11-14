"""Client brief: a one-page PDF per company."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app import common
from app.common import footer, setup
from secanalyst.outputs.brief import brief_content, brief_pdf

setup("Client brief")
st.title("Client brief")
st.caption(
    "A one-page A4 PDF for a client conversation: key metrics against the peer median, the "
    "top risks with their filing citations, what changed in the latest 10-K and the red flags."
)


@st.cache_data(show_spinner="Building the brief...")
def build(ticker: str) -> bytes:
    return brief_pdf(ticker, common.get_con(), common.get_index_chunks())


companies = {c.ticker: c.name for c in common.get_companies()}
ticker = st.selectbox(
    "Company", list(companies), format_func=lambda t: f"{t} - {companies[t]}", key="brief_company"
)
pdf = build(ticker)
st.download_button(
    "Download the brief (PDF)",
    data=pdf,
    file_name=f"{ticker}_client_brief.pdf",
    mime="application/pdf",
    key="brief_download",
)

c = brief_content(ticker, common.get_con(), common.get_index_chunks())
st.subheader("Preview")
st.dataframe(
    {"Metric": [m[0] for m in c.metrics], ticker: [m[1] for m in c.metrics],
     "Peer median": [m[2] for m in c.metrics]},
    width="stretch",
    hide_index=True,
)  # fmt: skip
st.markdown("**Top risks**")
for text, cit in c.risks:
    st.markdown(f"- {text}")
    st.badge(cit)
st.markdown("**What changed in the latest 10-K**")
st.write(c.changes)

footer()
