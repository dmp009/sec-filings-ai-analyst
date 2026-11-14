# Methodology

Data as of 2026-11-13. Calibration notes with the numbers behind each threshold:
[design/risk-diligence-notes.md](design/risk-diligence-notes.md).

## 1. Data

- **Source.** SEC EDGAR: the submissions API, the XBRL company-facts API and the filing documents
  (`ingest`). Raw files are timestamped under `data/raw/` (not committed); the committed data is the
  parquet snapshot in `data/snapshot/`, so the app runs without network.
- **Scope.** 8 companies, 24 10-Ks (latest three each) and 7 10-Qs (latest one when it follows the
  latest 10-K; Apple has none), 254 sections, 4,376 chunks.
- **SEC fair access.** Requests are rate-limited (8 per second at most), retried with back-off and
  sent with a User-Agent that names a contact. The contact is read from the environment or a local
  `.env` (`SEC_CONTACT`), which is git-ignored. It is never in the repository.
- **Fiscal years.** A fiscal-year label is the year in which the fiscal year ends, from the
  filing's own cover data. Apple ends in September, Microsoft in June, NVIDIA in late January,
  Broadcom around 1 November, the others in December. The quality check `fiscal_label_mismatch`
  compares the label with the period end. Columns are never calendar-aligned.

## 2. Parsing and chunking

Each filing is split into items (10-K: Items 1, 1A, 1C, 3, 7, 9A and others; 10-Q: Part I Item 2,
Part II Item 1A, and so on). Sections are cut into chunks of about 320 words with a 60-word
overlap (`config/settings.yaml`). A chunk id is `TICKER-FORM-YEAR-ITEM-POSITION`.

## 3. Retrieval

- **Hybrid search.** BM25 (rank-bm25, stop words removed) and cosine similarity on
  `BAAI/bge-small-en-v1.5` embeddings (384 dimensions, float16) each rank 50 candidates; the two
  rankings are fused with reciprocal-rank fusion (k = 60). Filters (company, year, form, item)
  are applied before ranking.
- **Cross-year deduplication.** Risk factors are repeated almost word for word from one year to
  the next. Chunks whose 5-gram Jaccard similarity is at least 0.8 collapse into one hit, kept for
  the latest year, with the other years listed ("also in FY...").
- **Out-of-scope guard.** A cosine floor of 0.60 (calibrated on the evaluation set: at least 0.62
  for all 30 questions, at most 0.55 for off-topic queries) and a lexical floor (0.55) for the
  BM25-only fallback; share-price and "should I buy" questions are caught by patterns, because
  they are semantically close to real passages.

### Evaluation

30 questions written by the author from the filings, each with the expected company, fiscal year,
item and a key phrase. A hit counts only if all four match. Every question targets a latest-year
filing.

| Filters set | recall@5 | MRR |
|---|--:|--:|
| company + fiscal year | 0.767 | 0.645 |
| company only | 0.567 | 0.335 |
| none | 0.467 | 0.263 |

Why unfiltered search scores lower: the index holds three years of each 10-K, eight companies
and the same topics (export controls, cyber, customers) in several items. The metric asks for a
specific company, year and item, while the engine only sees the question. Without filters,
a passage from another company, an older year whose wording differs slightly or the same topic in
another item can outrank the labelled one. The strict label (company, year, item and phrase) penalises a retrieved passage that is
relevant but not the labelled one, so the unfiltered figures understate usefulness somewhat; this
is not measured here. Filters are
what a user sets in the app, which is why the first line is the headline figure.

## 4. Financial definitions

Computed deterministically from XBRL facts (`fact_financials`); a missing input gives n/a, a
meaningless result gives n/m, each with a reason. Nothing is imputed. Year-end balances, 365-day
year. Full list in `secanalyst/financials/ratios.py` and in the app tooltips.

| Ratio | Definition |
|---|---|
| Revenue growth | Revenue / prior-year revenue - 1 |
| Gross, operating, net margin | Gross profit (tag, else revenue - cost of revenue), operating income, net income, over revenue |
| FCF, FCF margin, FCF conversion | FCF = operating cash flow - capex; margin over revenue; conversion over net income (n/m if net income <= 0) |
| ROIC | NOPAT / invested capital. NOPAT = operating income x (1 - tax rate), rate = income tax / pretax income clamped to 0-35 % |
| ROE | Net income / year-end equity (n/m if equity <= 0) |
| Net cash | Liquidity - total debt |
| Debt / EBITDA | Total debt / (operating income + D&A), n/m if EBITDA <= 0 |
| DSO, DIO, DPO, CCC | Receivables / revenue x 365; inventory / cost of revenue x 365; payables / cost of revenue x 365; DSO + DIO - DPO |

Rulings, decided once and applied to every company:

1. **Leases.** Operating leases are excluded from debt. Finance leases are included: from
   `FinanceLeaseLiabilityCurrent` and `...Noncurrent`, or from the total `FinanceLeaseLiability`
   when neither part is tagged (Microsoft). Broadcom's (and Alphabet's for FY2021-22) `LongTermDebtAndCapitalLeaseObligations`
   already includes the non-current finance leases, so they are not added twice. The check
   `debt_without_finance_leases` flags a company whose debt has no lease part although one is
   reported.
2. **Liquidity** is cash, short-term investments and marketable securities. `LongTermInvestments` is
   excluded (for Microsoft it is mostly equity-method and non-marketable equity).
3. **ROIC is n/m when invested capital is below 10 % of total assets.** Apple FY2022 ($2.6bn
   against $352.8bn of assets), FY2023 ($12.2bn against $352.6bn) and FY2024 ($7.8bn against
   $365.0bn): the ratio would be dominated by netting cash against debt and equity. Apple FY2026 is
   reported (231 %), because invested capital is above the threshold; read it with care.
4. **D&A.** Alphabet, Tesla and Microsoft report depreciation, with amortization of intangibles
   missing or minor; the ratio is kept. When a company reports depreciation only in a year but
   material intangibles amortization in other years, the year is withheld: Broadcom FY2021-22 have
   debt / EBITDA n/a.
5. **Amazon capex** is gross purchases of property and equipment; finance-lease additions are not
   deducted, so FCF is not reduced by them.

Data-quality status on this run: 0 errors, 3 warnings (Broadcom D&A FY2021-22, Alphabet inventory
FY2023-25, Meta inventory FY2021-25). See `data_quality_report.md`.

## 5. Risk-factor diff

Item 1A of the latest two 10-Ks is split into risks (heading line + paragraph; Title Case headings
for Amazon; a paragraph fallback for Microsoft). Risks are matched one-to-one, best cosine first,
on title plus the first 160 words. Cosine >= 0.90 means the same risk; below 0.97 or below 0.85 shared
distinct words means reworded; otherwise a minor edit, or identical when the text is the same
after whitespace normalisation. The thresholds come from a hand check of about 10 pairs for each
of Apple and NVIDIA. Limit: a risk that a filer splits or merges between years appears as one new
plus one removed.

## 6. Red-flag radar

Eight categories (material weakness and going concern have no hits in these filings), defined in
`config/red_flags.yaml`: AI regulation, China, customer concentration, cybersecurity, export
controls, litigation, material weakness, going concern. A hit is a 10-K passage of at least 300 characters in
the category's items with a keyword in a core sentence; enumerations (four or more commas,
semicolons or bullets) count only if they name the topic twice; Item 3 "see Note X" pointers are
dropped. Cybersecurity is restricted to Item 1A (Item 1C governance text matched wrongly).
Customer concentration is parsed separately ("X% of revenue").

**Precision** is the share of sampled hits whose core sentence is really about the topic.

| Round | Sample | Precision | Status |
|---|---|---|---|
| Original keywords | 39 | 0.41 | in-sample |
| Items + regex keywords | 33 | 0.79 | in-sample |
| Tuned config | 40 | 0.85 | in-sample, not a valid estimate (an independent draw of 8 gave 0.4-0.5) |
| Tightened rules | 40 | 0.825 | out-of-sample, led to the cybersecurity fix |
| Final | 40 | **0.875 (35/40)** | out-of-sample holdout, drawn after the last rule change |

One labeller (the author); 40 labels give an interval of about +/-0.10, so the final figure reads
as roughly 0.75 to 0.95. Per category on the holdout: AI regulation 7/7, China 6/7, customer
concentration 6/7, cybersecurity 6/7, export controls 5/6, litigation 5/6. Recall is not measured.

## 7. AI layer

- **Without a key (default).** The Ask page retrieves passages and returns the most relevant
  verbatim sentences of those passages, each with its citation, labelled "extractive". Nothing is
  generated.
- **With a key (optional).** `ANTHROPIC_API_KEY` in the environment (or Streamlit secrets)
  enables a drafted answer (model in `config/settings.yaml`), written through a forced tool call
  that returns an answer and the chunk ids it relies on.
- **Verification.** The answer is rejected unless (a) it has at least one citation, (b) every
  citation is among the retrieved chunks and (c) every number in the answer appears in a cited
  passage with the same value, scale (thousand, million, billion), percent flag and sign
  (a negative figure needs a negative figure in the source). One retry, then nothing is shown.
  Only verified answers are cached. Numbers written out in words ("two billion") are not
  checked, only digits.
- **Cost control.** A daily cap on calls (`daily_llm_cap`, 50) is kept in a local counter. It is
  best effort: on Streamlit Community Cloud the file system is ephemeral and the counter resets on
  restart. If you deploy with a key, set a monthly spend limit in the Anthropic console, which is
  the real safeguard.
- **Status.** No drafted answers are committed yet; `fact_ai_answers` is empty.

## 8. Limitations

- Eight large US technology companies; not a sample of the market.
- Fiscal years differ. Latest fiscal year means FY2026 for Apple and Microsoft, FY2026 (ended
  January 2026) for NVIDIA, FY2025 for the others, so a "latest" comparison mixes periods.
- XBRL tag gaps: companies tag the same item differently or not at all (Alphabet and Meta report no
  inventory, Broadcom D&A is missing for two years). Those ratios are n/a; the tag maps may still
  miss a tag used by a filer.
- The evaluation set is small (30), written and labelled by the author, and only covers latest
  filings. Recall figures carry a wide error band.
- The radar is keyword-based: it finds passages that name a topic, not risks that are described
  without the keyword. Precision comes from one labeller and 40 hits; recall is unknown.
- Risk diff compares only the latest two 10-Ks; layout changes show as new plus removed.
- No LLM answers are committed: the drafted-answer path is tested with a fake client and has not
  been shown on real filings in this repository.
- Educational project, not investment advice.
