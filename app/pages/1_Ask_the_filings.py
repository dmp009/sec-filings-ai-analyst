"""Ask the filings: hybrid search over 10-K/10-Q sections with extractive, cited answers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app import common
from app.common import footer, get_settings, setup
from secanalyst.answer import llm
from secanalyst.answer.extractive import answer, citation
from secanalyst.config import load_questions

setup("Ask the filings")
st.title("Ask the filings")
st.caption(
    "Search the text of the 10-K and 10-Q filings. Answers are passages and sentences quoted "
    "from the filings, each with its source; nothing is written by an AI."
)

index = common.get_index()
embedder = common.get_embedder()
settings = get_settings()
if embedder is None:
    st.info(
        "The semantic search model could not be loaded here, so this page uses keyword (BM25) "
        "search only. Results are less robust to wording."
    )

chunks = index.chunks
ALL = "All"
c1, c2, c3, c4 = st.columns(4)
company_options = [ALL] + sorted(chunks["ticker"].unique())
company = c1.selectbox("Company", company_options, key="f_company")
year = c2.selectbox(
    "Fiscal year", [ALL] + sorted(chunks["fiscal_year"].unique(), reverse=True), key="f_year"
)
form = c3.selectbox("Form", [ALL] + sorted(chunks["form"].unique()), key="f_form")
item = c4.selectbox("Item", [ALL] + sorted(chunks["item"].unique()), key="f_item")

questions = load_questions()
st.caption("Example questions")
cols = st.columns(2)
for i, q in enumerate(questions):

    def _pick(q=q):
        st.session_state["question"] = q["question"]
        t = q["ticker"]
        st.session_state["f_company"] = t if t in company_options else ALL

    cols[i % 2].button(q["question"], key=f"ex_{q['id']}", on_click=_pick, width="stretch")

query = st.text_input(
    "Your question", key="question", placeholder="e.g. How do export controls affect NVIDIA?"
)

if query.strip():
    filters = {
        k: v for k, v in {"ticker": company, "fy": year, "form": form, "item": item}.items()
        if v != ALL
    }  # fmt: skip
    res = answer(
        index, query, embedder, filters, k=settings.top_k,
        score_floor=settings.score_floor, lexical_floor=settings.lexical_floor,
        out_of_scope_patterns=settings.out_of_scope_patterns,
    )  # fmt: skip
    if res.message:
        st.warning(res.message)
    else:
        draft = None
        try:
            key = llm.get_api_key()
            draft = llm.answer_cached(
                query, res.hits, llm.AnthropicClient(settings.llm_model, key) if key else None,
                cap=settings.daily_llm_cap,
            )  # fmt: skip
        except Exception:  # noqa: BLE001
            draft = None  # never block the page; extractive answers stay
        if draft:
            st.subheader("AI-drafted answer (verified against the cited passages)")
            st.write(draft.answer)
            by_id = {h.chunk_id: h for h in res.hits}
            for cid in draft.citations:
                st.badge(citation(by_id[cid]))
        st.subheader("Key sentences (extractive, not AI-written)")
        for s in res.sentences:
            st.markdown(f"> {s.text}")
            st.badge(s.citation)
        st.subheader("Top passages")
        for h in res.hits:
            with st.expander(citation(h) + f"  ·  relevance {h.relevance:.2f}"):
                st.badge(citation(h))
                if h.also_in:
                    st.caption("also in " + ", ".join(f"FY{y}" for y in h.also_in))
                st.write(h.text)

footer()
