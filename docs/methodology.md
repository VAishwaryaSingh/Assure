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
