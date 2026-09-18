# Bugs and detection — the short version

Everything is **synthetic** (1,500 loans, fixed seed 42). Numbers re-verified 2026-09-18 by re-running the scripts in
[`2-process/run-logs/`](./2-process/run-logs/); the committed result files came out byte-identical.

## 1. Bugs found and fixed: 1

| # | What went wrong | How it was found | Fix | What guards it now |
|---|---|---|---|---|
| 1 | **556 of 1,500 loans (37%) had already fully matured before the reporting date.** The data generator drew origination dates without regard to loan term, so a "current" loan book contained finished loans. | While building the amortisation engine (Phase 3) and checking its output | Fixed at the source in [`generate_portfolio.py`](../data/generate_portfolio.py) — origination now bounded by each loan's own term — and both data files regenerated. Not filtered out afterwards. | Data-quality check `no_matured_loans_in_book` (0 violations now) |

Found by the developer while building, not by an independent reviewer. Write-up:
[`docs/methodology.md`](../docs/methodology.md), [Model Validation Memo §3](../assurance/model_validation_memo.md).

## 2. What the system detects

| Check | What it catches | Result |
|---|---|---|
| **Data quality — 9 checks** ([`data_quality_checks.py`](../assurance/data_quality_checks.py)) | Duplicate loan IDs · unexpected nulls · wrong `ltv` null pattern · out-of-range values · invalid categories · matured loans in a current book · orphan schedule rows · loans missing a schedule · loan IDs differing between files | **9 / 9 pass**, 0 violations across 1,500 loans |
| **Independent recalculation** ([`recalculation_test.py`](../assurance/recalculation_test.py)) | Production code drifting from the documented method — 25 loans rebuilt from scratch in a separate implementation | **25 / 25** balances and **25 / 25** ECL match within £0.01 |
| **Reconciliation 1** ([`reconciliation.py`](../assurance/reconciliation.py)) | Loan-level ECL not adding to the portfolio total | £2,041,659.41 = £2,041,659.41, difference **£0.00** |
| **Reconciliation 2** (same script) | A 3-month ECL roll-forward that doesn't balance | £1,939,299.16 opening + £277,821.75 new − £175,461.50 remeasurement = £2,041,659.41, difference **£0.00** |
| **Sensitivity** ([`sensitivity_analysis.py`](../assurance/sensitivity_analysis.py)) | Wrong direction or implausible size of response to shocks | PD ±20% → −12.81% / +12.75%; LGD ±20% → exactly −20% / +20%. Direction and size as expected (not pass/fail) |

## 3. What it does not detect

Stated plainly, so nobody has to discover it:

- **Only one of the nine data checks is known to have fired on bad data** (the matured-loans bug above). The other
  eight pass on the current clean data, and there is no record of them being tested against deliberately corrupted data.
- **PD and LGD are not validated.** They are authored assumptions, not calibrated to any bank's history, so a wrong
  assumption would pass every check here.
- **No downgrade-based SICR trigger, and the roll-forward cannot show stage migration.** Only one arrears snapshot exists.
- **The reviewer is not independent of the developer** — both are the same person. This limits the standing of the review
  ([memo §7](../assurance/model_validation_memo.md)).
- **Not covered:** how realistic the synthetic data is against real portfolios, regulatory capital, IFRS 9 disclosure notes.

Verdict in the memo: sound for a portfolio demonstration, **not** a production credit-risk tool.
