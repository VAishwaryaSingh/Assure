"""Phase 6 — recalculation testing.

This is an audit "test of detail" applied to code instead of a ledger:
take a random sample of loans, independently recompute their balance and
ECL from the source data and the documented formulas (docs/methodology.md)
— written fresh here, deliberately NOT by importing model/amortisation.py
or model/ecl.py — then compare against what the model actually produced.
An independent recompute that calls the same production code would prove
nothing; the point is to catch a bug where the code diverges from what the
methodology document says it does.

Run from the assure/ folder: `python assurance/recalculation_test.py`
Writes assurance/recalculation_test_results.csv.
"""

from pathlib import Path

import pandas as pd

SAMPLE_SIZE = 25
SAMPLE_SEED = 123  # deliberately different from the data generator's seed (42)
REPORTING_DATE = pd.Timestamp("2025-12-31")
TOLERANCE = 0.01  # GBP; a discrepancy above this is a genuine finding, not rounding

# Independently re-typed from docs/methodology.md, not imported from model/ecl.py.
PD_12M_BY_GRADE = {
    "AAA": 0.0005, "AA": 0.0010, "A": 0.0025, "BBB": 0.0050, "BB": 0.0150,
    "B": 0.0350, "CCC": 0.0800, "CC": 0.1500, "C": 0.2500, "D": 0.4000,
}
LGD_BY_COLLATERAL = {
    "residential": 0.20, "commercial": 0.35, "other": 0.50, "unsecured": 0.65,
}


def independent_balance_as_of(principal, annual_rate, term_months, amortisation_type,
                                origination_date, as_of_date) -> float:
    """Re-derived reducing-balance/bullet schedule, walked month by month."""
    c = annual_rate / 12
    if amortisation_type == "bullet":
        pmt = principal * c
    else:
        factor = (1 + c) ** term_months
        pmt = principal * (c * factor) / (factor - 1) if c else principal / term_months

    balance = principal
    date = pd.Timestamp(origination_date)
    for period in range(1, term_months + 1):
        date = pd.Timestamp(origination_date) + pd.DateOffset(months=period)
        if date > as_of_date:
            break
        interest = balance * c
        if amortisation_type == "bullet":
            principal_paid = balance if period == term_months else 0.0
        else:
            principal_paid = balance if period == term_months else pmt - interest
        balance -= principal_paid
    return balance


def independent_stage(arrears_days: int) -> int:
    if arrears_days >= 90:
        return 3
    if arrears_days >= 30:
        return 2
    return 1


def independent_ecl(loan, schedules_for_loan) -> float:
    grade = loan["borrower_risk_grade"]
    collateral = loan["collateral_type"]
    pd_12m = PD_12M_BY_GRADE[grade]
    lgd = LGD_BY_COLLATERAL[collateral]
    ead = loan["_recomputed_balance"]
    stage = independent_stage(loan["arrears_days"])

    if stage == 1:
        return pd_12m * lgd * ead
    if stage == 3:
        return lgd * ead

    # Stage 2 — lifetime ECL via the same survival-curve method described in
    # docs/methodology.md, re-derived independently rather than imported.
    monthly_hazard = 1 - (1 - pd_12m) ** (1 / 12)
    future = schedules_for_loan[schedules_for_loan["payment_date"] > REPORTING_DATE].sort_values("period")
    total = 0.0
    for months_ahead, opening_balance in enumerate(future["opening_balance"]):
        survival = (1 - monthly_hazard) ** months_ahead
        marginal_pd = survival * monthly_hazard
        total += marginal_pd * lgd * opening_balance
    return total


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")
    schedules = pd.read_parquet(base / "data" / "amortisation_schedules.parquet")
    ecl_results = pd.read_parquet(base / "data" / "ecl_results.parquet").set_index("loan_id")

    sample = portfolio.sample(n=SAMPLE_SIZE, random_state=SAMPLE_SEED).copy()

    rows = []
    for _, loan in sample.iterrows():
        recomputed_balance = independent_balance_as_of(
            loan["principal"], loan["interest_rate"], int(loan["term_months"]),
            loan["amortisation_type"], loan["origination_date"], REPORTING_DATE,
        )
        loan_dict = loan.to_dict()
        loan_dict["_recomputed_balance"] = recomputed_balance
        schedules_for_loan = schedules[schedules["loan_id"] == loan["loan_id"]]
        recomputed_ecl = independent_ecl(loan_dict, schedules_for_loan)

        model_balance = loan["current_balance"]
        model_ecl = ecl_results.loc[loan["loan_id"], "ecl"]

        balance_diff = recomputed_balance - model_balance
        ecl_diff = recomputed_ecl - model_ecl

        rows.append({
            "loan_id": loan["loan_id"],
            "model_balance": round(model_balance, 2),
            "recomputed_balance": round(recomputed_balance, 2),
            "balance_diff": round(balance_diff, 2),
            "balance_match": abs(balance_diff) <= TOLERANCE,
            "model_ecl": round(model_ecl, 2),
            "recomputed_ecl": round(recomputed_ecl, 2),
            "ecl_diff": round(ecl_diff, 2),
            "ecl_match": abs(ecl_diff) <= TOLERANCE,
        })

    results = pd.DataFrame(rows)
    out_path = Path(__file__).resolve().parent / "recalculation_test_results.csv"
    results.to_csv(out_path, index=False)

    balance_pass = results["balance_match"].sum()
    ecl_pass = results["ecl_match"].sum()
    print(f"Recalculation test: {SAMPLE_SIZE} loans sampled (seed={SAMPLE_SEED})")
    print(f"Balance recompute matches model: {balance_pass}/{SAMPLE_SIZE}")
    print(f"ECL recompute matches model:     {ecl_pass}/{SAMPLE_SIZE}")

    mismatches = results[~(results["balance_match"] & results["ecl_match"])]
    if len(mismatches):
        print(f"\n{len(mismatches)} discrepancy(ies) found:")
        print(mismatches)
    else:
        print("\nNo discrepancies found — every sampled loan's independently recomputed "
              "balance and ECL matches the model's output within £0.01.")

    print(f"\nFull results -> {out_path}")
