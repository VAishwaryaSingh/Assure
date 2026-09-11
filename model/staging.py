"""Phase 4 — IFRS 9 Stage 1/2/3 classification.

Uses IFRS 9's own days-past-due backstop rule (a "rebuttable presumption"
the standard explicitly permits when a more granular SICR model isn't
available — see docs/methodology.md for why that's the honest description
of what's implemented here, not a shortcut dressed up as something fancier):

  Stage 1 — performing, <30 days past due       -> 12-month ECL
  Stage 2 — significant increase in credit risk,
            30-89 days past due                 -> lifetime ECL
  Stage 3 — default, 90+ days past due           -> lifetime ECL, specific provisioning

Run from the assure/ folder: `python model/staging.py`
"""

from pathlib import Path

import pandas as pd


def assign_stage(arrears_days: int) -> int:
    if arrears_days >= 90:
        return 3
    if arrears_days >= 30:
        return 2
    return 1


def stage_portfolio(portfolio: pd.DataFrame) -> pd.DataFrame:
    df = portfolio.copy()
    df["ifrs9_stage"] = df["arrears_days"].apply(assign_stage)
    return df


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")
    staged = stage_portfolio(portfolio)

    counts = staged["ifrs9_stage"].value_counts().sort_index()
    exposure = staged.groupby("ifrs9_stage")["current_balance"].sum()
    print("Loans by stage:")
    print(counts)
    print("\nExposure (current_balance) by stage:")
    print(exposure.round(2))
