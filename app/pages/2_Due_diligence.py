"""Due diligence: risk-factor changes between the latest two 10-Ks and the red-flag radar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app import common
from app.common import footer, setup
from secanalyst.answer.extractive import filing_citation
from secanalyst.diligence.redflags import CATEGORY_LABELS, risk_citation

setup("Due diligence")
st.title("Due diligence")
st.caption(
    "What changed in the risk factors (Item 1A) between each company's latest two 10-Ks, and "
    "where the filings mention red-flag topics. Everything is computed from the filing text "
    "when the data is built; passages are quoted, nothing is written by an AI."
)

diff, rad, chunks = common.get_risk_diff(), common.get_radar(), common.get_chunks()
period = chunks.groupby(["ticker", "fiscal_year"])["period_end"].first().to_dict()


def cite(ticker: str, fy: str) -> str:
    return risk_citation(ticker, fy, period.get((ticker, fy), ""))


tab_diff, tab_radar = st.tabs(["Risk-factor changes", "Red-flag radar"])

with tab_diff:
    tickers = sorted(diff["ticker"].unique())
    missing = sorted(set(chunks["ticker"].unique()) - set(tickers))
    ticker = st.selectbox("Company", tickers, key="dd_company")
    d = diff[diff["ticker"] == ticker]
    fy_prev, fy_curr = d["fy_prev"].iloc[0], d["fy_curr"].iloc[0]
    st.markdown(f"**{ticker}: 10-K FY{fy_prev} compared with 10-K FY{fy_curr}**")
    counts = d["status"].value_counts()
    cols = st.columns(5)
    for col, (status, label) in zip(
        cols,
        [
            ("new", "New"),
            ("removed", "Removed"),
            ("changed", "Reworded"),
            ("minor", "Minor edits"),
            ("unchanged", "Identical"),
        ],
        strict=True,
    ):
        col.metric(label, int(counts.get(status, 0)))
    if missing:
        st.caption(f"Not compared (no usable Item 1A in two 10-Ks): {', '.join(missing)}.")
    st.caption(
        "Risks are matched one-to-one by embedding similarity of their opening text. A matched "
        "risk is Identical when the text is the same apart from whitespace, a Minor edit when "
        "it was edited but stays close (high embedding similarity and at least 85% of its "
        "words shared) and Reworded when it differs more. Section layouts differ between companies, so a split or merged risk can appear as new plus "
        "removed."
    )

    def show(df, prev=False, both=False):
        if df.empty:
            st.info("None.")
        for r in df.itertuples():
            title = r.prev_title if prev else r.curr_title
            with st.expander(title):
                if both:
                    st.caption(f"Embedding similarity {r.similarity:.3f}")
                    a, b = st.columns(2)
                    a.markdown(f"**FY{fy_prev}**")
                    a.write(r.prev_text)
                    b.markdown(f"**FY{fy_curr}**")
                    b.write(r.curr_text)
                    st.badge(cite(ticker, fy_curr))
                else:
                    st.write(r.prev_text if prev else r.curr_text)
                    st.badge(cite(ticker, fy_prev if prev else fy_curr))

    t_new, t_rem, t_chg, t_min = st.tabs(
        ["New risks", "Removed risks", "Reworded risks", "Minor edits"]
    )
    with t_new:
        show(d[d["status"] == "new"])
    with t_rem:
        show(d[d["status"] == "removed"], prev=True)
    with t_chg:
        show(d[d["status"] == "changed"].sort_values("similarity"), both=True)
    with t_min:
        show(d[d["status"] == "minor"].sort_values("similarity"), both=True)

with tab_radar:
    st.markdown("**Passages per topic, latest 10-K of each company**")
    latest = rad.sort_values("fy").groupby(["ticker", "category"]).tail(1)
    grid = latest.pivot(index="ticker", columns="category", values="hits").reindex(
        columns=list(CATEGORY_LABELS)
    )
    grid = grid.reindex(sorted(chunks["ticker"].unique())).fillna(0).astype(int)
    grid.columns = [CATEGORY_LABELS[c] for c in grid.columns]
    grid.index.name = "Company"
    st.dataframe(grid, width="stretch")
    st.caption(
        "Number of 10-K passages (about 320 words each) in the relevant Items that match the "
        "topic's keywords (config/red_flags.yaml). A count shows where to read, not how bad "
        "it is; measured precision on a fresh sample of 40 hits was 0.83 (docs/design/radar_labelled_hits.csv), weakest for cybersecurity because Item 1C governance text also matches. Zero means no match, e.g. no company discloses a material weakness or going "
        "concern doubt in these filings."
    )

    c1, c2 = st.columns(2)
    names = {v: k for k, v in CATEGORY_LABELS.items()}
    cat = names[c2.selectbox("Topic", [CATEGORY_LABELS[c] for c in CATEGORY_LABELS], key="dd_cat")]
    rt = c1.selectbox("Company ", sorted(chunks["ticker"].unique()), key="dd_radar_company")
    sel = rad[(rad["ticker"] == rt) & (rad["category"] == cat)].sort_values("fy", ascending=False)
    if sel.empty:
        st.info(f"No {CATEGORY_LABELS[cat].lower()} passages for {rt}.")
    by_id = chunks.set_index("chunk_id")
    for r in sel.itertuples():
        with st.expander(f"FY{r.fy}: {r.hits} passage(s)"):
            for cid in r.chunk_ids[:5]:
                row = by_id.loc[cid]
                st.badge(filing_citation(rt, "10-K", r.fy, row["item"], row["period_end"]))
                st.write(row["text"])
            if len(r.chunk_ids) > 5:
                st.caption(f"{len(r.chunk_ids) - 5} more passage(s) not shown.")

    st.markdown("**Customer concentration (single customers)**")
    cc = common.get_customer_concentration()
    if cc.empty:
        st.info("No single-customer percentages found.")
    else:
        view = cc.rename(
            columns={"ticker": "Company", "fy": "Fiscal year", "percent": "% of revenue",
                     "citation": "Source"}
        )  # fmt: skip
        st.dataframe(view, width="stretch", hide_index=True)
    st.caption(
        "Parsed from sentences such as 'one customer accounted for 28% of net revenue'. "
        "Distributor, top-five and geographic shares are not single customers and are left out."
    )

footer()
