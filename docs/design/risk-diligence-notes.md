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

Statuses of a matched pair: identical (same text after whitespace normalisation), minor edit
(edited but above `risk_change` and `risk_lexical`), reworded (below either bar). Microsoft's
paragraph fallback merges fragments (lowercase or date starts, lines without final punctuation).

Counts (new / removed / reworded / minor edits / identical), latest two 10-Ks:
AAPL 1/0/14/11/2, AMZN 0/0/0/14/9, AVGO 4/4/16/17/3, GOOGL 2/2/10/12/1, META 0/0/7/20/13,
MSFT 13/2/24/25/20, NVDA 5/2/2/14/5, TSLA 2/3/9/21/7. (Earlier "same" counts hid edits: AMZN
rewrites sat at 0.89-0.98 word overlap.)

Limitations: layouts differ, so a risk that a filer splits or merges between years shows as
new plus removed; Microsoft is compared paragraph by paragraph.

## Red-flag radar precision

Radar hits are 10-K passages (at least 300 characters) whose Item is in the category's `items`,
that match one keyword (`config/red_flags.yaml`) in a core sentence (a sentence with 4 or more
commas, semicolons or bullets is an enumeration and only counts if it names the topic twice), and
that are not Item 3 "see Note X" pointers. China needs China/Chinese/PRC/Taiwan/Hong Kong; bare
"geopolitical", "tariffs" and "antitrust" are not keywords.

Precision = share of sampled hits where the core sentence is really about the topic.

| Round | Sample | Precision | Note |
|---|---|---|---|
| 1 original keywords | 39 | 0.41 | in-sample, used for tuning |
| 2 Items + regex keywords | 33 | 0.79 | in-sample, used for tuning |
| 3 "final" tuned config | 40 | 0.85 | in-sample: not a valid estimate; an independent 8-hit draw by the reviewer gave 0.4-0.5 (generic geopolitical lists, Russia/Ukraine, "antitrust and import/export regulations", cyber as one item in a list, Item 3 pointer stubs) |
| 4 tightened rules | 40, fresh seed 2024, never used for tuning | 0.825 (33/40) | out-of-sample; cyber 3/7 because Item 1C governance text matched, which led to round 5 (`round` 1 in the CSV) |
| 5 cybersecurity restricted to Item 1A (final) | 40, fresh seed 777, drawn after the last rule change, no overlap with round 4 | **0.875 (35/40)** | out-of-sample; `round` 2 in `radar_labelled_hits.csv` |

Per category in the round-5 holdout: AI regulation 7/7, China 6/7, customer concentration 6/7,
cybersecurity 6/7, export controls 5/6, litigation 5/6. Remaining false positives: a privacy-law
mention of China, a "no customer reached 10%" sentence, topics that are only one entry in a list.
40 labels carry a wide interval (about +/-0.10), so read 0.875 as "roughly 0.75 to 0.95". Labels were assigned by one reader (the author).

Customer concentration is parsed separately (single or direct customers, "X% of revenue"):
NVDA FY2024 13% and 19% (indirect), FY2025 12% and 11%, FY2026 22% and 14%; AVGO FY2023 21%,
FY2024 28%, FY2025 32% (a distributor).
