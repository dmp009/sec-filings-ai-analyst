# Data dictionary

Every table and column of `secanalyst/warehouse/schema.sql`. Money is in USD, not scaled.
The relations are in [data_model.md](data_model.md).

## dim_company

One row per company (from `config/companies.yaml`).

| Column | Type | Description |
|---|---|---|
| ticker | VARCHAR, PK | Stock ticker, for example AAPL |
| name | VARCHAR | Company name as in EDGAR |
| cik | VARCHAR | SEC Central Index Key, 10 digits with leading zeros |
| fy_end_month | INTEGER | Month in which the fiscal year ends (Apple 9, Microsoft 6, NVIDIA 1, Broadcom 10, others 12) |

## fact_filings

One row per filing kept (latest three 10-Ks and the latest 10-Q of each company).

| Column | Type | Description |
|---|---|---|
| filing_id | VARCHAR, PK | Accession number |
| ticker | VARCHAR | Company |
| form | VARCHAR | `10-K` or `10-Q` |
| accession | VARCHAR | Accession number as published by the SEC |
| filing_date | DATE | Date the filing was accepted |
| period_end | DATE | End of the reporting period (`dei:DocumentPeriodEndDate`) |
| fiscal_year_label | VARCHAR | Fiscal year label of the filing (`dei:DocumentFiscalYearFocus`) |

## fact_sections

One row per item of a filing (Item 1, 1A, 1C, 3, 7, 9A, 10-Q Part I Item 2, and so on).

| Column | Type | Description |
|---|---|---|
| filing_id | VARCHAR, PK | Filing the section belongs to |
| ticker | VARCHAR | Company |
| form | VARCHAR | `10-K` or `10-Q` |
| fiscal_year | VARCHAR | Fiscal year label of the filing |
| item | VARCHAR, PK | Item code: `1`, `1A`, ... for 10-K; `P1-2`, `P2-1A` for 10-Q |
| title | VARCHAR | Item heading when found |
| text | VARCHAR | Plain text of the section |
| n_chars | INTEGER | Length of `text` in characters |

## fact_financials

One row per (company, fiscal year, concept), taken from XBRL company facts.

| Column | Type | Description |
|---|---|---|
| ticker | VARCHAR, PK | Company |
| fiscal_year_label | VARCHAR, PK | Fiscal year label |
| period_end | DATE | End of the fiscal year |
| concept | VARCHAR, PK | Internal concept name (`revenue`, `capex`, `total_debt`, `liquidity`, ...) mapped in `config/xbrl_tags.yaml` |
| value | DOUBLE | Value in USD |
| tag | VARCHAR | XBRL tag used, or a `sum:` / `fallback:` path when the value is derived |
| accession | VARCHAR | Source filing; comma-separated when derived from several |

## fact_ratios

One row per (company, fiscal year, ratio): 15 ratios, 40 company-years.

| Column | Type | Description |
|---|---|---|
| ticker | VARCHAR, PK | Company |
| fiscal_year_label | VARCHAR, PK | Fiscal year label |
| period_end | DATE | End of the fiscal year |
| ratio | VARCHAR, PK | Ratio name (`revenue_growth`, `gross_margin`, `operating_margin`, `net_margin`, `fcf_margin`, `fcf_conversion`, `capex_intensity`, `roic`, `roe`, `net_cash`, `debt_to_ebitda`, `dso`, `dio`, `dpo`, `ccc`) |
| value | DOUBLE | Ratio value; null unless status is `ok`. Fractions (0.25 = 25 %), days, or USD for `net_cash` |
| status | VARCHAR | `ok`, `n/a` (an input is missing) or `n/m` (not meaningful); checked by the schema |
| reason | VARCHAR | Why the ratio is not `ok` (required then) |

## fact_chunks

Passage-level text for search. Declared here; the populated copy is `data/snapshot/chunks.parquet`.

| Column | Type | Description |
|---|---|---|
| chunk_id | VARCHAR, PK | `ticker/form/year/item/position`, for example `NVDA-10-K-2026-1A-0058` |
| filing_id | VARCHAR | Source filing |
| ticker | VARCHAR | Company |
| form | VARCHAR | `10-K` or `10-Q` |
| fiscal_year | VARCHAR | Fiscal year label |
| item | VARCHAR | Item code |
| position | INTEGER | Order of the chunk within the item |
| text | VARCHAR | About 320 words, 60 words of overlap with the previous chunk |
| n_words | INTEGER | Word count of `text` |

## fact_ai_answers

Verified drafted answers (none committed yet).

| Column | Type | Description |
|---|---|---|
| cache_key | VARCHAR, PK | Hash of question, retrieved chunk ids and prompt version |
| question_id | VARCHAR | Id of the example question, when there is one |
| question | VARCHAR | Question text |
| answer_json | VARCHAR | JSON with the answer and its citations (chunk ids) |
| model | VARCHAR | Model that drafted the answer |
| prompt_version | VARCHAR | Prompt template version (`answer_v1`) |
| created_at | TIMESTAMP | Creation time |

## meta

| Column | Type | Description |
|---|---|---|
| key | VARCHAR, PK | `as_of` (data date, 2026-11-13) or `fetched_at` (download timestamp) |
| value | VARCHAR | Value |

## Snapshot files outside the warehouse

| File | Columns | Description |
|---|---|---|
| `risk_diff.parquet` | ticker, fy_prev, fy_curr, status, prev_title, prev_text, curr_title, curr_text, similarity | One row per risk factor of the latest two 10-Ks: new, removed, reworded, minor edit, identical |
| `radar.parquet` | ticker, fy, category, hits, chunk_ids | Red-flag radar: hit count and passages per company, year and category |
| `vectors.npy` | one row per chunk | bge-small-en-v1.5 embeddings, float16, same order as `chunks.parquet` |
