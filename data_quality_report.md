# Data quality report

Data as of 2026-11-13 (SEC EDGAR).

0 error(s), 3 warning(s).

| Severity | Check | Ticker | Detail |
|---|---|---|---|
| warning | missing_concept | AVGO | depreciation_amortization missing for FY2021, FY2022 |
| warning | missing_concept | GOOGL | inventory missing for FY2023, FY2024, FY2025 |
| warning | missing_concept | META | inventory missing for FY2021, FY2022, FY2023, FY2024, FY2025 |

## Checks run

| Check | Severity | What it detects |
|---|---|---|
| `tenk_missing_item` | error | 10-K whose Item 1A or Item 7 is missing or empty |
| `filing_without_sections` | error | filing with no section rows |
| `tenq_missing_mdna` | warning | 10-Q without Part I Item 2 (MD&A) |
| `section_length` | warning | Item 1A or 7 shorter than 5,000 chars, or a section longer than 1,000,000 chars |
| `duplicate_section` | error | the same text in two items of one filing |
| `fiscal_label_mismatch` | error | fiscal-year label differs from the fiscal year containing the period end (10-K: also the period-end year) |
| `financials_years` | error | company with fewer than 5 fiscal years of revenue |
| `missing_concept` | warning | core concept missing in a company-year (ratios using it are n/a, never imputed) |
| `ratio_schema` | error | fact_ratios row breaking the schema: known ratio, status in ok / n/a / n/m, value iff ok, reason when not ok |
| `financials_schema` | error | fact_financials row with empty tag or accession |
| `debt_without_finance_leases` | warning | total debt has no finance-lease component although FinanceLeaseLiability is reported |

## Row counts

| Table | Rows |
|---|---|
| dim_company | 8 |
| fact_filings | 31 |
| fact_sections | 254 |
| fact_financials | 1095 |
| fact_ratios | 600 |
| fact_chunks | 0 (declared, empty; passages are stored in chunks.parquet: 4,376) |
| fact_ai_answers | 0 |
| meta | 2 |

## Key ratios, latest fiscal year

Fiscal years differ (Apple ends in September, Microsoft in June, NVIDIA in January, Broadcom in October/November): compare by fiscal-year label and check the period end. `n/a` = input concept missing, `n/m` = not meaningful.

| Ticker | FY | Period end | Rev. growth | Gross margin | Op. margin | FCF margin | FCF conv. | ROIC | ROE | Net cash ($bn) | Debt/EBITDA | CCC (days) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 2026 | 2026-09-26 | 15.1% | 48.8% | 33.0% | 28.4% | 102.9% | 231.3% | 117.9% | 55.4 | 0.48x | -67 |
| AMZN | 2025 | 2025-12-31 | 12.4% | 50.3% | 11.2% | 1.1% | 9.9% | 17.4% | 18.9% | 41.9 | 0.56x | -51 |
| AVGO | 2025 | 2025-11-02 | 23.9% | 67.8% | 39.9% | 42.1% | 116.4% | 19.6% | 28.4% | -49.0 | 1.91x | 53 |
| GOOGL | 2025 | 2025-12-31 | 15.1% | 59.7% | 32.0% | 18.2% | 55.4% | 31.6% | 31.8% | 75.8 | 0.34x | n/a |
| META | 2025 | 2025-12-31 | 22.2% | 82.0% | 41.4% | 22.9% | 76.3% | 30.0% | 27.8% | 21.7 | 0.59x | n/a |
| MSFT | 2026 | 2026-06-30 | 17.8% | 67.9% | 46.8% | 20.2% | 50.1% | 26.5% | 30.2% | -30.0 | 0.55x | -52 |
| NVDA | 2026 | 2026-01-25 | 65.5% | 71.1% | 60.4% | 44.8% | 80.5% | 89.3% | 76.3% | 33.4 | 0.06x | 133 |
| TSLA | 2025 | 2025-12-31 | -2.9% | 18.0% | 4.6% | 6.6% | 163.9% | 6.8% | 4.6% | 35.7 | 0.89x | 13 |

## Ratios not computed

| Ratio | Status | Reason | Company-years |
|---|---|---|---|
| ccc | n/a | missing concept inventory | GOOGL FY2023, GOOGL FY2024, GOOGL FY2025, META FY2021, META FY2022, META FY2023, META FY2024, META FY2025 |
| debt_to_ebitda | n/a | missing concept depreciation_amortization | AVGO FY2021, AVGO FY2022 |
| dio | n/a | missing concept inventory | GOOGL FY2023, GOOGL FY2024, GOOGL FY2025, META FY2021, META FY2022, META FY2023, META FY2024, META FY2025 |
| fcf_conversion | n/m | net income <= 0 (-2,722,000,000) | AMZN FY2022 |
| revenue_growth | n/a | missing concept revenue (prior fiscal year) | AAPL FY2022, AMZN FY2021, AVGO FY2021, GOOGL FY2021, META FY2021, MSFT FY2022, NVDA FY2022, TSLA FY2021 |
| roic | n/m | invested capital $12.2bn < 10% of total assets ($352.6bn); ROIC dominated by cash netting | AAPL FY2023 |
| roic | n/m | invested capital $2.6bn < 10% of total assets ($352.8bn); ROIC dominated by cash netting | AAPL FY2022 |
| roic | n/m | invested capital $7.8bn < 10% of total assets ($365.0bn); ROIC dominated by cash netting | AAPL FY2024 |
