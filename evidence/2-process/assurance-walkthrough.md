# Process: from data to a reviewed model

The order the work was done in, and the file behind each step. Every step has a script you can re-run, and the assurance
steps have captured output in [`run-logs/`](./run-logs/). All data is synthetic (seed `42`).

| Step | What happens | Script | Output |
|---|---|---|---|
| 1. Data | 1,500 synthetic loans generated reproducibly | [`data/generate_portfolio.py`](../../data/generate_portfolio.py) | `loan_portfolio.parquet` — [profile](../1-data/portfolio-profile.md) |
| 2. Amortisation | Monthly reducing-balance / bullet schedules (~180k rows), used to refresh each loan's current balance | [`model/amortisation.py`](../../model/amortisation.py) | `amortisation_schedules.parquet` |
| 3. Staging + ECL | IFRS 9 Stage 1/2/3; 12-month ECL (Stage 1), lifetime (Stage 2), direct loss (Stage 3) | [`model/staging.py`](../../model/staging.py), [`model/ecl.py`](../../model/ecl.py) | `ecl_results.parquet` |
| 4. Scenarios | Base / adverse / severe, probability-weighted 60 / 30 / 10 | [`model/scenarios.py`](../../model/scenarios.py) | `ecl_scenarios.parquet` |
| 5. Assurance | 9 data checks · 25-loan independent recalculation · 2 reconciliations · sensitivity tests | [`assurance/`](../../assurance/) | [run logs](./run-logs/) |
| 6. Review | Written like a model-risk validation memo, limitations included | — | [`model_validation_memo.md`](../../assurance/model_validation_memo.md) |
| 7. Dashboard | Four tabs reading the committed outputs only — no calculation in the dashboard, so it can't drift from the model | [`app/dashboard.py`](../../app/dashboard.py) | [Live dashboard](https://assurebcm.streamlit.app/) |

## Where the process caught its own mistake

At step 2, checking the amortisation output showed 37% of loans were already matured — a flaw in step 1. It was fixed at
the source (not patched downstream), both files regenerated, and a permanent check added to step 5. Details:
[bugs-and-detection.md](../bugs-and-detection.md).

## Design choices worth knowing

- **Independence of the recalculation.** [`recalculation_test.py`](../../assurance/recalculation_test.py) is written
  separately and does not import the production model — calling the same code twice cannot find a bug in it. It uses its
  own sample seed (`123`, versus `42` for the data).
- **Fixed seeds everywhere**, so every number on these pages can be reproduced.

## Reproduce

```bash
pip install -r requirements.txt
python assurance/data_quality_checks.py
python assurance/recalculation_test.py
python assurance/reconciliation.py
python assurance/sensitivity_analysis.py
```

Running the model and generator scripts too rewrites the committed data files; the four assurance scripts above only
rewrite their own result files, and on 2026-09-18 those came out identical to what is committed.
