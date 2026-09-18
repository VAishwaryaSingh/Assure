# Outcome: what the model produced, and what the review concluded

Everything is synthetic, so these are **demonstration results, not findings about a real bank**. Numbers re-verified
2026-09-18 ([run logs](../2-process/run-logs/)).

## The result

| | |
|---|---|
| Portfolio | 1,500 synthetic loans, **£65.6m** current balance |
| Base-case ECL | **£2.04m — 3.11% coverage** (Stage 1: 1.94% · Stage 2: 10.25% · Stage 3: 42.91%) |
| Probability-weighted ECL | **£2.43m** (base £2.04m · adverse £2.69m · severe £4.00m; weighted 60 / 30 / 10) |

Full breakdown: [data profile](../1-data/portfolio-profile.md) · [live dashboard](https://assurebcm.streamlit.app/).

## Did the model pass its own review?

| Test | Result |
|---|---|
| Data quality (9 checks) | 9 / 9 pass |
| Independent recalculation (25 loans) | 25 / 25 balances, 25 / 25 ECL within £0.01 |
| Loan-level ECL vs. portfolio total | Ties, £0.00 difference |
| 3-month ECL roll-forward | Balances, £0.00 difference |
| Sensitivity to PD and LGD | Expected direction and size; PD response slightly sub-linear because Stage 3 loss is a fixed LGD × EAD term ([memo §6](../../assurance/model_validation_memo.md)) |

## The memo's conclusion — and its limit

> Within the scope this review actually covers — code correctness, data integrity, and internal consistency — **I would
> sign this model off as fit for the purpose it was built for: a portfolio demonstration, not a production credit-risk
> tool.** [...] It should not be read as validating the PD/LGD calibration itself, which [...] was never in scope.
>
> — [Model Validation Memo §8](../../assurance/model_validation_memo.md) (abridged)

What the review cannot claim is listed in [bugs-and-detection.md](../bugs-and-detection.md#3-what-it-does-not-detect):
authored PD/LGD, no downgrade trigger, and a reviewer who is also the developer.

## What went wrong along the way

One real bug, found and fixed: 37% of loans in the first data version were already matured. It is now guarded by a
permanent data check. See [bugs-and-detection.md](../bugs-and-detection.md#1-bugs-found-and-fixed-1).
