"""Phase 3 — monthly amortisation schedule engine.

Builds the real month-by-month repayment schedule for a loan using the
standard reducing-balance annuity formula (plan.md Section 6):

    P = L x [c(1+c)^n] / [(1+c)^n - 1]

where L = principal, c = monthly interest rate, n = term in months.

Two amortisation types are supported, matching the `amortisation_type`
field generated in Phase 2:
  - reducing_balance: payment amount is flat each month; the interest vs.
    principal split shifts as the balance falls (an ordinary loan/mortgage).
  - bullet: interest-only every month, full principal repaid at maturity.

Run from the assure/ folder: `python model/amortisation.py`
Rebuilds data/amortisation_schedules.parquet and refreshes the
`current_balance` column in data/loan_portfolio.parquet with the real
computed value (replacing the Phase 2 straight-line placeholder).
"""

from pathlib import Path

import numpy as np
import pandas as pd


def monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
    c = annual_rate / 12
    if c == 0:
        return principal / term_months
    factor = (1 + c) ** term_months
    return principal * (c * factor) / (factor - 1)


def amortisation_schedule(
    loan_id: str,
    principal: float,
    annual_rate: float,
    term_months: int,
    origination_date,
    amortisation_type: str,
) -> pd.DataFrame:
    """One row per monthly period, first payment one month after origination."""
    origination_date = pd.Timestamp(origination_date)
    c = annual_rate / 12
    periods = range(1, term_months + 1)
    balance = principal
    rows = []

    pmt = principal * c if amortisation_type == "bullet" else monthly_payment(
        principal, annual_rate, term_months
    )

    for p in periods:
        date = origination_date + pd.DateOffset(months=p)
        interest = balance * c

        if amortisation_type == "bullet":
            principal_paid = balance if p == term_months else 0.0
        else:
            principal_paid = balance if p == term_months else pmt - interest
        # Final period always forces exact payoff, so floating-point drift
        # never leaves a residual balance of a few pence at maturity.

        payment = principal_paid + interest
        closing = balance - principal_paid
        rows.append((loan_id, p, date, balance, payment, interest, principal_paid, closing))
        balance = closing

    return pd.DataFrame(rows, columns=[
        "loan_id", "period", "payment_date", "opening_balance",
        "payment", "interest_amount", "principal_amount", "closing_balance",
    ])


def build_all_schedules(portfolio: pd.DataFrame) -> pd.DataFrame:
    frames = [
        amortisation_schedule(
            row.loan_id, row.principal, row.interest_rate, int(row.term_months),
            row.origination_date, row.amortisation_type,
        )
        for row in portfolio.itertuples()
    ]
    return pd.concat(frames, ignore_index=True)


def balance_as_of(portfolio: pd.DataFrame, schedules: pd.DataFrame, as_of_date) -> pd.DataFrame:
    """Real current_balance per loan: closing balance at the last payment on/before as_of_date.

    Loans originated so recently that no payment has fallen due yet are
    still at full principal — handled explicitly rather than left null.
    """
    as_of_date = pd.Timestamp(as_of_date)
    past = schedules[schedules["payment_date"] <= as_of_date]
    latest = (
        past.sort_values("period")
        .groupby("loan_id")
        .tail(1)[["loan_id", "period", "payment_date", "closing_balance"]]
        .rename(columns={"closing_balance": "current_balance", "period": "periods_elapsed"})
    )

    result = portfolio[["loan_id", "principal"]].merge(latest, on="loan_id", how="left")
    no_payment_yet = result["current_balance"].isna()
    result.loc[no_payment_yet, "current_balance"] = result.loc[no_payment_yet, "principal"]
    result.loc[no_payment_yet, "periods_elapsed"] = 0
    return result.drop(columns="principal")


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")

    schedules = build_all_schedules(portfolio)
    schedules_path = base / "data" / "amortisation_schedules.parquet"
    schedules.to_parquet(schedules_path, index=False)
    print(f"Built {len(schedules):,} schedule rows across {len(portfolio)} loans -> {schedules_path}")

    REPORTING_DATE = pd.Timestamp("2025-12-31")
    balances = balance_as_of(portfolio, schedules, REPORTING_DATE)

    portfolio = portfolio.drop(columns=["current_balance"]).merge(
        balances[["loan_id", "current_balance"]], on="loan_id", how="left"
    )
    portfolio_path = base / "data" / "loan_portfolio.parquet"
    portfolio.to_parquet(portfolio_path, index=False)
    print(f"Refreshed current_balance for {len(portfolio)} loans -> {portfolio_path}")

    sample_id = portfolio.iloc[0]["loan_id"]
    print(f"\nSample schedule for {sample_id}:")
    print(schedules[schedules["loan_id"] == sample_id].head())
