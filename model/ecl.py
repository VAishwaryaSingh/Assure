"""Phase 4 — PD x LGD x EAD -> Expected Credit Loss (ECL).

Formulas (plan.md Section 6):
  12-month ECL (Stage 1): PD_12m x LGD x EAD
  Lifetime ECL (Stage 2):  sum over remaining months of (PD_t x LGD x EAD_t)
  Stage 3 (defaulted):     LGD x EAD directly — the loss event has already
                           happened, so there's nothing left to project a
                           future default probability for.

Run from the assure/ folder: `python model/ecl.py`
"""

from pathlib import Path

import numpy as np
import pandas as pd

from staging import stage_portfolio

# 12-month PD by risk grade. Illustrative, shaped loosely like the order of
# magnitude of published rating-agency average annual default rates — not
# calibrated to any specific real study. See docs/methodology.md.
PD_12M_BY_GRADE = {
    "AAA": 0.0005, "AA": 0.0010, "A": 0.0025, "BBB": 0.0050, "BB": 0.0150,
    "B": 0.0350, "CCC": 0.0800, "CC": 0.1500, "C": 0.2500, "D": 0.4000,
}

# LGD by collateral type — secured lending recovers more in a default, so a
# lower proportion of the exposure is ultimately lost.
LGD_BY_COLLATERAL = {
    "residential": 0.20, "commercial": 0.35, "other": 0.50, "unsecured": 0.65,
}


def _monthly_hazard(annual_pd: float) -> float:
    """Constant monthly default hazard implied by a constant annual PD."""
    return 1 - (1 - annual_pd) ** (1 / 12)


def ecl_12_month(
    portfolio: pd.DataFrame,
    pd_table: dict = PD_12M_BY_GRADE,
    lgd_table: dict = LGD_BY_COLLATERAL,
) -> pd.Series:
    pd_12m = portfolio["borrower_risk_grade"].map(pd_table)
    lgd = portfolio["collateral_type"].map(lgd_table)
    ead = portfolio["current_balance"]
    return pd_12m * lgd * ead


def ecl_lifetime(
    portfolio: pd.DataFrame,
    schedules: pd.DataFrame,
    as_of_date,
    pd_table: dict = PD_12M_BY_GRADE,
    lgd_table: dict = LGD_BY_COLLATERAL,
) -> pd.Series:
    """Sum of PD_t x LGD x EAD_t over every remaining monthly period."""
    as_of_date = pd.Timestamp(as_of_date)
    future = (
        schedules[schedules["payment_date"] > as_of_date]
        .sort_values(["loan_id", "period"])
        .merge(portfolio[["loan_id", "borrower_risk_grade", "collateral_type"]], on="loan_id")
    )

    annual_pd = future["borrower_risk_grade"].map(pd_table)
    monthly_hazard = annual_pd.apply(_monthly_hazard)
    months_ahead = future.groupby("loan_id").cumcount()  # 0 = the next period after as_of_date
    survival_prob = (1 - monthly_hazard) ** months_ahead
    marginal_pd = survival_prob * monthly_hazard  # unconditional P(default in exactly this month)
    lgd = future["collateral_type"].map(lgd_table)

    # EAD_t = the balance outstanding going into that period (opening_balance),
    # i.e. the exposure actually at risk during that month.
    period_ecl = marginal_pd * lgd * future["opening_balance"]
    lifetime = period_ecl.groupby(future["loan_id"]).sum()
    return portfolio["loan_id"].map(lifetime).fillna(0.0)


def ecl_stage3(portfolio: pd.DataFrame, lgd_table: dict = LGD_BY_COLLATERAL) -> pd.Series:
    lgd = portfolio["collateral_type"].map(lgd_table)
    ead = portfolio["current_balance"]
    return lgd * ead


def calculate_ecl(
    portfolio: pd.DataFrame,
    schedules: pd.DataFrame,
    as_of_date,
    pd_table: dict = PD_12M_BY_GRADE,
    lgd_table: dict = LGD_BY_COLLATERAL,
) -> pd.DataFrame:
    """Adds ifrs9_stage and ecl columns, routing each loan to the right formula by stage.

    `pd_table`/`lgd_table` default to the base-case tables but can be swapped
    for scaled versions — see model/scenarios.py and
    assurance/sensitivity_analysis.py — to flex the same calculation under
    different macro scenarios or sensitivity shocks. Stage assignment always
    uses arrears_days (a fact about the loan), never these tables, so which
    stage a loan sits in doesn't change — only its ECL does.
    """
    df = stage_portfolio(portfolio)
    ecl_12m = ecl_12_month(df, pd_table, lgd_table)
    ecl_life = ecl_lifetime(df, schedules, as_of_date, pd_table, lgd_table)
    ecl_s3 = ecl_stage3(df, lgd_table)

    df["ecl"] = np.select(
        [df["ifrs9_stage"] == 1, df["ifrs9_stage"] == 2, df["ifrs9_stage"] == 3],
        [ecl_12m, ecl_life, ecl_s3],
    )
    return df


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")
    schedules = pd.read_parquet(base / "data" / "amortisation_schedules.parquet")
    REPORTING_DATE = pd.Timestamp("2025-12-31")

    result = calculate_ecl(portfolio, schedules, REPORTING_DATE)

    out_path = base / "data" / "ecl_results.parquet"
    result.to_parquet(out_path, index=False)
    print(f"Calculated ECL for {len(result)} loans -> {out_path}")

    summary = result.groupby("ifrs9_stage").agg(
        loans=("loan_id", "count"),
        exposure=("current_balance", "sum"),
        ecl=("ecl", "sum"),
    ).round(2)
    summary["coverage_ratio_%"] = (summary["ecl"] / summary["exposure"] * 100).round(3)
    print("\nECL summary by stage:")
    print(summary)
    print(f"\nTotal portfolio ECL: {result['ecl'].sum():,.2f}")
    print(f"Total exposure:      {result['current_balance'].sum():,.2f}")
