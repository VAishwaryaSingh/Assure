# Model Validation Memo — Assure ECL Model

**Model reviewed:** `assure` synthetic loan portfolio IFRS 9 expected credit loss (ECL) model
**Reporting date:** 31 December 2025
**Reviewer:** Aishwarya Singh
**Review date:** *(fill in on publish)*

---

## 1. Scope

This review covers the ECL model built in `model/` (amortisation, IFRS 9 staging, ECL
calculation, and scenario engine) and the synthetic loan portfolio it runs on
(`data/loan_portfolio.parquet`, 1,500 loans). It assesses: the soundness of the
methodology, the quality of the underlying data, whether the model's calculations can
be independently reproduced, whether its outputs reconcile internally, and how
sensitive the headline ECL figure is to its key assumptions.

**Explicitly out of scope**, and not claimed otherwise:
- Calibration of PD/LGD to any real bank's historical loss experience — every
  probability and loss rate in this model is an authored, disclosed assumption (see
  `docs/methodology.md`), not derived from actual default data.
- Regulatory capital, IFRS 9 disclosure notes, or any prudential overlay.
- Independent model governance sign-off. This review was performed by the same
  person who built the model — a real bank's model risk function requires the
  reviewer to be independent of the developer, which is not the case here. This is a
  material limitation on the review's standing, not a technicality, and is restated
  in Section 7.

## 2. Methodology assessed

The model takes a synthetic book of 1,500 loans and, for each, builds a real monthly
amortisation schedule (`model/amortisation.py`), classifies it into an IFRS 9 stage
using the standard 30/90 days-past-due backstop (`model/staging.py`), and calculates
an expected credit loss (`model/ecl.py`):

- **Stage 1** (performing): `12-month ECL = PD_12m × LGD × EAD`
- **Stage 2** (watch-listed): lifetime ECL, summing a monthly marginal default
  probability (derived from the grade's annual PD via a constant-hazard survival
  curve) × LGD × the loan's projected balance in that month, across its entire
  remaining schedule
- **Stage 3** (defaulted): `LGD × EAD` directly — the loss event has already occurred

A scenario engine (`model/scenarios.py`) re-runs this calculation under base/adverse/
severe macro assumptions (PD scaled ×1.0/×1.5/×2.5) and combines them into a
probability-weighted figure. Full formulas, PD/LGD tables, and every simplifying
assumption are documented in `docs/methodology.md` — this memo does not repeat them,
only assesses them.

**Assessment:** the methodology is internally consistent and mirrors real IFRS 9
practice (the days-past-due backstop is a rule the standard itself permits; the
staged 12-month/lifetime split, and the marginal-PD survival-curve approach to
lifetime ECL, are standard techniques). The main methodological gap is the missing
risk-grade-downgrade SICR trigger (plan.md's alternative Stage 2 criterion) — not
implemented because the synthetic data has no risk-grade history to test it against.
This is disclosed in `docs/methodology.md` and repeated in Section 7 below.

## 3. Data quality findings

`assurance/data_quality_checks.py` runs 9 independent checks — duplicate `loan_id`s,
unexpected nulls, the `ltv` null pattern, out-of-range values (negative balances, LTV
over 100%, interest rate over 50%, etc.), categorical validity, no matured loans in
the book, and referential integrity across the three derived data files.

**Result: 9/9 passed**, 0 violations across all 1,500 loans. Full results:
`assurance/data_quality_results.json`.

One check — "no matured loans in the book" — exists specifically because it caught a
real defect during development: an earlier version of the data generator produced
origination dates independently of loan term, leaving 556 of 1,500 loans (37%)
already fully matured before the reporting date. That was fixed at the source (see
`docs/methodology.md`, Phase 2/3), and this check now guards against it recurring.
Surfacing that here rather than only in the methodology doc is deliberate: a
validation review should report what it actually caught, not just what currently
passes.

## 4. Recalculation testing

A sample of 25 loans (fixed seed, `assurance/recalculation_test.py`) had their
balance and ECL **independently recalculated from the source data and the documented
formulas** — written fresh in the test script, not by re-calling the production
code — then compared to the model's own output. This is directly equivalent to an
audit test of detail: independently redoing a calculation from source data to see if
the preparer's figure agrees, applied here to code instead of a ledger.

**Result: 25/25 loans matched on both balance and ECL, within a £0.01 tolerance.**
Full results: `assurance/recalculation_test_results.csv`.

No discrepancies were found. This is evidence the production code correctly
implements what `docs/methodology.md` describes — it does not, on its own, validate
that the methodology itself is realistic (that's Section 2 and Section 7).

## 5. Reconciliation

`assurance/reconciliation.py` performs two checks:

**(a) Loan-level sum vs. portfolio total.** The sum of all 1,500 loans' individual
ECL figures ties exactly to the portfolio-level total (£2,041,659.41 both ways, £0.00
difference).

**(b) Opening-to-closing ECL roll-forward**, 30 Sep 2025 → 31 Dec 2025:

| | Loans | ECL |
|---|---|---|
| Opening | 1,379 | £1.94m |
| + New originations | 121 | +£0.28m |
| + Remeasurement (existing loans) | — | −£0.18m |
| − Derecognitions | 0 | £0.00 |
| **= Closing** | **1,500** | **£2.04m** |

**Result: reconciles exactly (£0.00 difference).** The negative remeasurement is a
genuine, sensible finding, not a plug: existing loans' balances amortise down over
the quarter, mechanically reducing their exposure and therefore their ECL, partially
offsetting the £0.28m added by new originations.

**Disclosed simplification:** the dataset has only one point-in-time arrears/status
snapshot, so this roll-forward cannot show genuine stage migration between the two
dates — the opening position holds each existing loan's stage constant and only rolls
its balance back in time. See `docs/methodology.md` Phase 6 for the full explanation.
This means the roll-forward proves the model's *arithmetic* ties together correctly;
it does not demonstrate the model would correctly track a loan moving between stages
over time, which a real bank's roll-forward would need to show.

## 6. Sensitivity / stress testing

Two complementary views, both against the £2.04m base-case ECL:

**PD/LGD flex, ±10%/±20%** (`assurance/sensitivity_analysis.py`):

| Shock | PD → ECL (Δ%) | LGD → ECL (Δ%) |
|---|---|---|
| −20% | £1.78m (−12.8%) | £1.63m (−20.0%) |
| −10% | £1.91m (−6.4%) | £1.84m (−10.0%) |
| +10% | £2.17m (+6.4%) | £2.25m (+10.0%) |
| +20% | £2.30m (+12.8%) | £2.45m (+20.0%) |

LGD sensitivity is exactly linear (ECL is directly proportional to LGD in every
formula used). PD sensitivity is sub-linear — a ±10% PD shock only moves ECL by
~±6.4% — because Stage 3's loss (`LGD × EAD`) has no PD term at all, so roughly a
third of total ECL doesn't respond to a PD shock.

**Macro scenarios, base/adverse/severe** (Phase 5, `model/scenarios.py`): PD scaled
×1.0/×1.5/×2.5 produces £2.04m / £2.69m / £4.00m, probability-weighted (60/30/10) to
**£2.43m — a 19.1% uplift over the base case alone.** Same sub-linearity applies, and
is explained in full in `docs/methodology.md`.

**Assessment:** the ECL figure is meaningfully sensitive to both PD and LGD, in the
direction and rough proportion expected, with no discontinuities or sign errors. The
sub-linearity in both tests has the same root cause (Stage 3's fixed LGD×EAD term),
which is a genuine finding worth flagging to a reader, not an artefact to smooth over.

## 7. Limitations & recommendations

What this project deliberately does not claim, and what a production version would
need:

1. **PD/LGD are authored assumptions, not calibrated to data.** A real model would
   need multi-year historical default and recovery data, segmented and back-tested.
2. **No risk-grade-downgrade SICR trigger.** Only the days-past-due backstop is
   implemented, because the synthetic data has no grade history to test a
   downgrade-based trigger against.
3. **The reconciliation roll-forward cannot show stage migration**, for the same
   reason — only one arrears snapshot exists.
4. **The reviewer is not independent of the model developer.** A real bank's model
   risk function requires this separation; this review does not have it, and that is
   a limitation on its standing, not just a disclosure.
5. **No regulatory capital overlay, no IFRS 9 disclosure-note preparation**, and no
   validation of the synthetic data generator's realism against actual portfolio
   composition benchmarks.
6. **Recommendation for a "next version":** obtain (or more carefully simulate) a
   time series of loan-level risk indicators across multiple periods, which would
   unlock a genuine stage-migration model, a real downgrade-based SICR trigger, and a
   roll-forward that actually demonstrates movement between stages rather than only
   balance runoff.

## 8. Conclusion

The model is arithmetically sound: recalculation testing found zero discrepancies
across an independent sample, both reconciliations tie exactly, and every data
quality check passes. Its sensitivity to PD and LGD behaves as expected, with a
well-understood, explainable cause for the one non-obvious result (sub-linear PD
sensitivity). Within the scope this review actually covers — code correctness, data
integrity, and internal consistency — **I would sign this model off as fit for the
purpose it was built for: a portfolio demonstration, not a production credit-risk
tool.** Its assumptions are disclosed rather than hidden, which is the standard this
review has tried to hold itself to throughout. It should not be read as validating
the PD/LGD calibration itself, which — as stated in Section 1 and Section 7 — was
never in scope.
