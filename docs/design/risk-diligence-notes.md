# Risk diff and red-flag radar: calibration notes

Calibrated 2026-11-14 on the committed snapshot (bge-small-en-v1.5 embeddings).

## Risk-factor diff

Item 1A of the latest two 10-Ks per company is split into risks (stand-alone one-sentence
heading lines followed by a longer paragraph; Title Case headings for Amazon; paragraph
fallback for Microsoft, whose headings are run into the text). Risks are matched one-to-one,
best cosine similarity first, on title plus the first 160 words.

| Threshold | Value | Meaning |
|---|---|---|
| `risk_match` | 0.90 | cosine at or above: same risk |
| `risk_change` | 0.97 | cosine below: reworded |
| `risk_lexical` | 0.85 | share of distinct words in common below: reworded |

Hand check of about 10 pairs each on AAPL (FY2025 vs FY2026) and NVDA (FY2025 vs FY2026):

- Genuine matches scored 0.915 to 1.000 (lowest: AAPL "technology industry... intense media,
  political and regulatory scrutiny", 0.915; AAPL cyber-incident risk reworded, 0.934).
- Non-matches scored 0.757 to 0.883 (NVDA "AI Diffusion IFR" risks against the new export-control
  paragraphs, 0.883 and 0.787; AAPL's new AI risk, 0.850). The first guess of 0.80 let the
  0.883 pair match wrongly, so the bar moved to 0.90.
- bge-small compresses similarity: matched pairs sit above 0.91 and the opening 160 words often
  stay identical while later text changes (NVDA acquisitions risk: cosine 1.000, word overlap
  0.37). Hence the extra lexical test; at 0.85 AAPL's stock-price risk (0.87, small edits) stays
  "same" and its regulatory-compliance risk (0.83, two new paragraphs of substance) is "reworded".

Counts (new / removed / reworded / same): AAPL 1/0/14/13, AMZN 0/0/0/23, AVGO 4/4/16/20,
GOOGL 2/2/10/13, META 0/0/7/33, MSFT 14/2/24/45, NVDA 5/2/2/19, TSLA 2/3/9/28.

Limitations: layouts differ, so a risk that a filer splits or merges between years shows as
new plus removed; Microsoft is compared paragraph by paragraph.

## Red-flag radar precision

Radar hits are 10-K passages whose Item is in the category's `items` and which match one
keyword (`config/red_flags.yaml`). Precision = share of sampled hits where a reader would say the
passage really discusses the topic as a risk or fact about the company.

| Round | Sample | Precision | Main false positives |
|---|---|---|---|
| 1 original keywords, all Items | 39 | 0.41 (16/39) | auditor boilerplate ("risk that a material weakness exists"), investee going-concern policy text, "responsible AI" marketing, "administrative sanctions", loan facility in China |
| 2 Items restricted, regex keywords, exclusions | 33 (only 33 hits available in the sampled strata) | 0.79 (26/33) | "GAIN AI Act" matched "AI Act", "single customer opportunity", hypothetical material-weakness sentence |
| 3 final config | 40 | **0.85 (34/40)** | bare "geopolitical" and China in facility lists (China category is the weakest, 3 of 7 right) |

Final sample: 7 hits from each of six categories (seeded random draw) plus the first four of
the seventh; material weakness and going concern have no hits in these filings (a correct
result), so they are not in the sample.

Customer concentration is parsed separately (single or direct customers, "X% of revenue"):
NVDA FY2024 13% and 19% (indirect), FY2025 12% and 11%, FY2026 22% and 14%; AVGO FY2023 21%,
FY2024 28%, FY2025 32% (a distributor).
