# Methodology

This document records every assumption made while building `assure`, so the model
is reproducible and its choices are disclosed rather than hidden — filled in as each
build phase progresses (see `plan.md`).

---

## Phase 2 — Synthetic loan portfolio (`data/generate_portfolio.py`)

**Reproducibility.** The generator uses a fixed random seed (`42`) for both `numpy`
and `Faker`. Running the script again produces byte-for-byte the same 1,500 loans —
this matters because a reviewer should be able to re-derive the dataset from the
script alone, not have to trust a static file.

**Portfolio size and reporting date.** 1,500 loans (within the 1,000–2,000 range the
plan calls for), snapshotted as at a fixed **reporting date of 31 Dec 2025**. Every
"current" field (`current_balance`, `arrears_days`, `status`) is a position as at
that date, not "today."

**Origination dates.** Drawn (via `Faker.date_between`) from up to 10 years before the
reporting date, so the book contains a realistic mix of recently originated and
long-standing loans — but bounded per loan by that loan's own term (with a 45-day
buffer), so every loan is guaranteed to still be active (not yet matured) as of the
reporting date. *(Correction made during Phase 3: the first version of this generator
drew origination dates independently of term, which left 556 of 1,500 loans — 37% —
already fully matured before the reporting date. A "current" loan book shouldn't
contain loans that already finished, so this was fixed before building the
amortisation engine on top of it.)*

**Term and maturity.** Term is drawn from a fixed set of common terms (1–30 years),
weighted toward shorter/medium terms. Maturity date is approximated as
`origination_date + term_months × 30 days`. This 30-days-per-month shortcut is a
deliberate Phase 2 simplification — Phase 3's amortisation engine uses real calendar
months instead, so maturity dates may shift slightly by a few days once that's built.

**Principal.** Drawn from a lognormal distribution (mean exponent 10.5, sigma 1.0),
clipped to £2,000–£3,000,000. Chosen because loan books are typically right-skewed —
many small loans, a long tail of large ones — rather than evenly spread.

**Risk grade and pricing.** A 10-point scale (`AAA` best → `D` worst), with
probabilities weighted so most of the book sits in investment-adjacent grades and only
a small tail is genuinely weak (2% `D`) — a plausible shape for a going-concern bank,
not a distressed one. Interest rate is set from a fixed base rate per grade (weaker
grade → higher rate, standard risk-based pricing) plus small random noise, clipped to
1%–20%.

**Industry sector and region.** Sector list mixes `Consumer/Retail` (weighted highest,
representing individual/retail borrowers) with commercial sectors (manufacturing,
healthcare, real estate, etc.). Region uses standard UK regions, chosen uniformly.
These are for portfolio concentration analysis (e.g. the sector × grade heatmap in
Phase 7) — they don't feed into the ECL maths itself.

**Collateral type and LTV.** `unsecured` / `residential` / `commercial` / `other`,
weighted 35/35/20/10. Loan-to-value (`ltv`) is only generated for `residential` and
`commercial` loans (drawn from a normal distribution centred on 65%, clipped to
10%–95%) and left null for `unsecured`/`other`, since LTV isn't a meaningful concept
without collateral.

**Current balance — originally a Phase 2 placeholder, now superseded.** Phase 2
initially calculated this as a straight-line decline from `principal`. As documented
below, Phase 3's amortisation engine has since replaced every value in this column
with the real, reducing-balance-calculated figure — see the Phase 3 section.

**Arrears and status.** `arrears_days` is drawn from a Poisson distribution whose rate
increases with weaker risk grade (so worse-graded borrowers are more likely to show
some arrears), plus a thin, deliberately-injected tail of genuinely distressed loans
(60–200 days past due) so the dataset contains real default cases to test the IFRS 9
staging logic against in Phase 4. `status` is then derived mechanically from
`arrears_days`: `<30` days = performing, `30–89` = watch, `90+` = default. (Note: this
`status` field is a simple descriptive label on the raw data, distinct from the formal
IFRS 9 Stage 1/2/3 classification built in Phase 4, which uses its own, separately
documented rule.)

**Known limitation, disclosed upfront:** every distribution and threshold above is an
authored, reasonable assumption for a synthetic dataset — not calibrated to any real
bank's actual portfolio or historical default experience. This is intentional (see
`plan.md` Section 7, point 1 — "Scope"), and is restated in the Model Validation
Memo's limitations section rather than hidden.

---

## Phase 3 — Amortisation engine (`model/amortisation.py`)

**Formula.** Standard reducing-balance annuity formula (plan.md Section 6):
`P = L × [c(1+c)^n] / [(1+c)^n − 1]`, where `L` = principal, `c` = monthly interest
rate (`annual_rate / 12`), `n` = term in months. This is the same maths a real bank
or mortgage lender uses to set a level monthly payment.

**Two schedule types**, matching the `amortisation_type` field from Phase 2:
- `reducing_balance` (85% of the book): one flat monthly payment for the life of the
  loan; the split between interest and principal repayment shifts every month as the
  balance falls — more interest early on, more principal later.
- `bullet` (15% of the book): interest-only every month, with the entire principal
  repaid in a single lump sum in the final period.

**First payment timing.** The first payment falls exactly one calendar month after
`origination_date` (using real calendar months via `pandas.DateOffset`, not the
30-days-per-month shortcut Phase 2's `maturity_date` field uses — a small, disclosed
inconsistency between the two date fields of at most a few days).

**Final-period exact payoff.** The last period of every schedule forces
`principal_amount` to equal the exact remaining balance, rather than trusting the
formula's output — this eliminates the few pence of floating-point rounding drift
that would otherwise leave a non-zero balance after the "final" payment. Verified: the
maximum closing balance at the final period, across all 1,500 loans, is exactly £0.00.

**`current_balance` refresh.** Running `model/amortisation.py` recalculates
`current_balance` in `data/loan_portfolio.parquet` from the real schedule — the
closing balance at the most recent payment date on/before the 31 Dec 2025 reporting
date — replacing the Phase 2 straight-line placeholder. Loans originated so recently
that no payment has fallen due yet correctly show `current_balance == principal`.

**Correction to Phase 2 discovered here:** building the real schedules surfaced that
556 of 1,500 loans (37%) had already fully matured before the reporting date under
the original Phase 2 date logic (see the "Origination dates" correction note above) —
a portfolio snapshot shouldn't include loans that already finished. Fixed at the
source in Phase 2's generator rather than filtered out afterwards, then both scripts
were re-run. Post-fix, every loan has a positive `current_balance` (minimum ~£509,
no loans at £0), and 0 loans are already matured as of the reporting date.

**New output file, not in the original plan.md layout:** `data/amortisation_schedules.parquet`
(180,084 rows — one per loan per remaining month, ~120 months average). Added because
Phase 4's lifetime ECL calculation needs each loan's full remaining monthly schedule
(plan.md Section 6: "summed over remaining amortisation schedule"), not just the
single current-balance figure.

---

## Phase 4 — IFRS 9 staging & ECL (`model/staging.py`, `model/ecl.py`)

**Staging rule.** Uses IFRS 9's own days-past-due backstop — a "rebuttable
presumption" the standard explicitly permits as a proxy for "significant increase in
credit risk" when a more granular internal model isn't available:
- Stage 1: `< 30` days past due → 12-month ECL
- Stage 2: `30-89` days past due → lifetime ECL
- Stage 3: `90+` days past due (default) → lifetime ECL, treated as a near-certain loss

**Disclosed limitation:** plan.md also lists "a risk-grade downgrade of 2+ notches
since origination" as an alternative Stage 2 trigger. That's not implemented — Phase
2's synthetic dataset only models a single, static risk grade per loan (as at
origination), not a grade *history* that could show migration over time. Modelling
grade drift honestly would need its own dedicated random process, which felt like
scope creep for this MVP. Noted here explicitly rather than silently dropped.

**PD (probability of default), 12-month, by risk grade** — a fixed lookup table,
loosely shaped like the *order of magnitude* of published rating-agency average
annual default rates (investment-grade under 1%, sub-investment-grade rising steeply
to 40% for the weakest grade). Not calibrated to any specific real study — the point,
per plan.md Section 5, is that it's defensible and disclosed, not realistic to a
specific bank's book.

**LGD (loss given default), by collateral type** — residential 20%, commercial 35%,
other 50%, unsecured 65%. Secured lending is assumed to recover more of its exposure
in a default (via collateral sale), so a lower share is ultimately lost. Illustrative,
same disclosure basis as PD.

**EAD (exposure at default).** For Stage 1 and Stage 3: the loan's current balance as
at the reporting date. For Stage 2's lifetime calculation: the *opening balance* of
each future monthly period — i.e. the exposure actually outstanding during the month
a default could occur in, taken from the real amortisation schedule (Phase 3), not a
static figure.

**12-month ECL (Stage 1):** `PD_12m x LGD x EAD`, applied once using the loan's
current balance — the direct formula from plan.md Section 6. *Known simplification:*
this isn't capped to a loan's remaining term, so a loan with only 2-3 months left
before maturity is given the full 12-month PD rather than a shorter, remaining-life
one — a minor, technically-correct-under-a-stricter-reading nuance, not corrected here
to keep the model matching the plan's stated formula exactly.

**Lifetime ECL (Stage 2):** walks every remaining monthly period from the
amortisation schedule and sums `PD_t x LGD x EAD_t`. `PD_t` is the *marginal* (this
specific month, unconditional) default probability, derived by converting the grade's
annual PD into a constant monthly hazard rate (`h = 1 − (1 − PD_annual)^(1/12)`) and
applying survival analysis: `PD_t = (1 − h)^(t−1) x h`. This treats the annual PD as
constant across the loan's remaining life — a standard, legible simplification (real
models often let PD vary by vintage or economic cycle; see Phase 5 for how this
project layers macro scenarios on top of the same PD table instead).

**Stage 3 ECL.** Deliberately *not* a forward PD projection — a defaulted loan's loss
event has already happened, so ECL is calculated directly as `LGD x EAD` (effectively
PD = 100%), consistent with "specific provisioning" in plan.md Section 5.

**Result (base case, no scenario overlay yet — see Phase 5), reporting date
31 Dec 2025:**

| Stage | Loans | Exposure | ECL | Coverage |
|---|---|---|---|---|
| 1 — performing | 1,431 | £62.89m | £1.22m | 1.94% |
| 2 — watch | 40 | £1.11m | £0.11m | 10.25% |
| 3 — default | 29 | £1.65m | £0.71m | 42.91% |
| **Total** | **1,500** | **£65.65m** | **£2.04m** | **3.11%** |

Saved to `data/ecl_results.parquet` (the Phase 2 portfolio fields, plus `ifrs9_stage`
and `ecl` per loan) — another output file not in the original plan.md layout, added
for the same reason as `amortisation_schedules.parquet`: it's the concrete,
inspectable result this phase actually produces.

---

## Phase 5 — Scenario engine (`model/scenarios.py`)

**Mechanism.** Re-runs the exact same Phase 4 calculation three times, with every risk
grade's PD scaled up by a fixed multiplier — a worse economy is modelled as a higher
chance of default, nothing else changes. `ifrs9_stage` does **not** change across
scenarios: which stage a loan sits in is a fact about its actual payment history
(`arrears_days`), not a macro assumption, in this simplified model — only the loss
number moves.

**PD multipliers — base 1.0x / adverse 1.5x / severe 2.5x.** Taken directly from
plan.md Section 5's own example values.

**Scenario probabilities — base 60% / adverse 30% / severe 10%.** This project's own
assumption, not a calibrated economic forecast: base-case-most-likely weighting is a
common convention in multi-scenario IFRS 9 ECL reporting. Disclosed here rather than
presented as if derived from real economic modelling.

**Probability-weighted ECL** = Σ(scenario ECL x scenario probability) across all
three — the single blended figure a bank would actually report, rather than picking
one scenario in isolation.

**Result, same reporting date and portfolio as Phase 4:**

| Scenario | PD multiplier | Probability | Total ECL | Coverage |
|---|---|---|---|---|
| Base | 1.0x | 60% | £2.04m | 3.11% |
| Adverse | 1.5x | 30% | £2.69m | 4.10% |
| Severe | 2.5x | 10% | £4.00m | 6.09% |
| **Probability-weighted** | — | — | **£2.43m** | — |

**Why the uplift isn't a clean 1.5x/2.5x:** Stage 3 loans are unaffected by the PD
multiplier at all (Phase 4's Stage 3 ECL is `LGD x EAD` directly — there's no PD term
to scale), so roughly a third of the base ECL is fixed regardless of scenario. The
remaining Stage 1/2 portion scales close to, but not exactly, the stated multiplier
because (a) the lifetime ECL survival-curve maths (Phase 4) is non-linear in PD, and
(b) PD is capped at 100% — the weakest grade (`D`, 40% base PD) hits that cap exactly
under the severe 2.5x multiplier. Worth being able to explain this out loud rather
than presenting the scaling as perfectly linear.

Saved to `data/ecl_scenarios.parquet` — all three scenarios' full per-loan results in
one file (a `scenario` column distinguishes them), for the dashboard's side-by-side
scenario view in Phase 7.
