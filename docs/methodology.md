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

**Origination dates.** Drawn uniformly at random (via `Faker.date_between`) from the
10 years up to the reporting date, so the book contains a realistic mix of recently
originated and long-standing loans.

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

**Current balance — Phase 2 placeholder.** Calculated as a **straight-line**
decline from `principal` based on the fraction of the loan's term elapsed by the
reporting date (bullet loans stay at full principal until maturity, since they don't
amortise). This is a disclosed simplification: it is *not* the real reducing-balance
amortisation maths — that's built properly in Phase 3, and `current_balance` will be
recalculated from the real schedule at that point rather than this approximation.

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
