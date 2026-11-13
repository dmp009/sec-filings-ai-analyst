"""Peer benchmarking on XBRL-derived ratios."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.benchmarking import FY_NOTE, RATIO_INFO, fmt_value, latest_ranking
from app.charts import ranking_bar, ratio_lines
from app.common import footer, get_financials, get_ratios, setup

setup("Benchmarking")
st.title("Benchmarking")
st.caption(FY_NOTE)

labels = {RATIO_INFO[k].label: k for k in RATIO_INFO}
choice = st.selectbox(
    "Ratio", list(labels), key="ratio_select", help="Definitions appear below the selector."
)
ratio = labels[choice]
st.info(f"**{choice}** ({RATIO_INFO[ratio].unit}): {RATIO_INFO[ratio].definition}")

df = get_ratios()
df = df[df["ratio"] == ratio].copy()
df["cell"] = [fmt_value(ratio, v, s) for v, s in zip(df["value"], df["status"], strict=True)]

st.subheader("Five fiscal years")
table = df.pivot(index="ticker", columns="fiscal_year_label", values="cell").fillna("")
table.index.name = "Company"
st.dataframe(table, width="stretch")
st.caption(
    "Columns are fiscal-year labels; an empty cell means the company has no such year in the "
    "five-year window. Period ends are in the expander below."
)
with st.expander("Fiscal-year end dates"):
    ends = df.pivot(index="ticker", columns="fiscal_year_label", values="period_end")
    st.dataframe(ends.apply(lambda c: c.dt.strftime("%Y-%m-%d")).fillna(""), width="stretch")
bad = df[df["status"] != "ok"].sort_values(["ticker", "fiscal_year_label"])
if len(bad):
    with st.expander(f"Why {len(bad)} values are n/a or n/m"):
        st.dataframe(
            bad[["ticker", "fiscal_year_label", "status", "reason"]].rename(
                columns={"ticker": "Company", "fiscal_year_label": "Fiscal year"}
            ),
            width="stretch",
            hide_index=True,
        )

st.plotly_chart(ratio_lines(df, ratio), width="stretch")

st.subheader("Latest fiscal year ranking")
ranked, median, label = latest_ranking(df)
if median is None:
    st.warning("No valid value for this ratio in the latest fiscal year.")
else:
    st.metric(f"Peer median ({len(ranked)} companies with a valid value)", fmt_value(ratio, median))
st.plotly_chart(ranking_bar(ranked, ratio, median), width="stretch")
if len(ranked):
    shown = ranked.assign(value_fmt=[fmt_value(ratio, v) for v in ranked["value"]])
    st.dataframe(
        shown[["ticker", "fiscal_year_label", "value_fmt"]].rename(
            columns={"ticker": "Company", "fiscal_year_label": "Fiscal year", "value_fmt": choice}
        ),
        width="stretch",
        hide_index=True,
    )
st.caption(
    "Each company is taken at its latest reported fiscal year; the median and ranking use "
    "valid values only (n/a and n/m are excluded)."
)

st.subheader("Source of a value")
c1, c2 = st.columns(2)
tickers = sorted(df["ticker"].unique())
t = c1.selectbox("Company", tickers, key="src_ticker")
years = sorted(df.loc[df["ticker"] == t, "fiscal_year_label"].unique(), reverse=True)
y = c2.selectbox("Fiscal year", years, key="src_year")
row = df[(df["ticker"] == t) & (df["fiscal_year_label"] == y)].iloc[0]
st.write(
    f"{choice}, {t} FY{y}: **{row['cell']}**" + (f" ({row['reason']})" if row["reason"] else "")
)
fin = get_financials()
src = fin[(fin["ticker"] == t) & (fin["fiscal_year_label"] == y)]
st.dataframe(
    src[["concept", "value", "tag", "accession"]].sort_values("concept"),
    width="stretch",
    hide_index=True,
)
st.caption(
    "All XBRL inputs for that company-year; the ratio uses the relevant ones (see definition)."
)

footer()
