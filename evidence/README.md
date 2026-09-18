# Evidence

A guided path through the proof behind Assure: **the data it works on, the process that produced the results, and the
outcome** — with links to the working files.

> **Everything here is synthetic.** The loan book is generated with a fixed seed (`42`); nothing reflects a real bank,
> borrower or portfolio. Numbers on these pages were re-verified on 2026-09-18.

## Start here — bugs and detection

**[bugs-and-detection.md](./bugs-and-detection.md)** — one page: the bug that was found and fixed, every check that
detects problems and what it found, and what the system does **not** detect.

## 1. Underlying data

| | |
|---|---|
| [Data profile](./1-data/portfolio-profile.md) | What is in the loan book, and the ECL it produced, by stage and scenario |
| [Sample loans](./1-data/portfolio-sample.csv) | The first 25 loans as a CSV |
| Full data | [`data/`](../data/) — four parquet files and the [generator](../data/generate_portfolio.py) |

## 2. Process

| | |
|---|---|
| [Data to reviewed model](./2-process/assurance-walkthrough.md) | The seven steps, the script behind each, and where the process caught its own mistake |
| [Run logs](./2-process/run-logs/) | Captured output of the four assurance scripts |
| [Methodology](../docs/methodology.md) | Every formula, assumption and disclosed simplification |

## 3. Outcome

| | |
|---|---|
| [Results summary](./3-outcome/results-summary.md) | £2.04m base / £2.43m weighted ECL, whether it passed its own review, and the memo's limits |
| [Model Validation Memo](../assurance/model_validation_memo.md) | The full model-risk-style write-up |
| [Live dashboard](https://assurebcm.streamlit.app/) | Four tabs, no login |

## Reproduce

```bash
pip install -r requirements.txt
python assurance/data_quality_checks.py
python assurance/recalculation_test.py
python assurance/reconciliation.py
python assurance/sensitivity_analysis.py
```
