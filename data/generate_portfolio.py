"""Phase 2 — synthetic loan portfolio generator.

Run from the assure/ folder: `python data/generate_portfolio.py`
Writes data/loan_portfolio.parquet. Every assumption/distribution choice
below is also written up in docs/methodology.md.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
N_LOANS = 1500
REPORTING_DATE = pd.Timestamp("2025-12-31")

RISK_GRADES = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "C", "D"]
RISK_GRADE_PROBS = [0.03, 0.06, 0.10, 0.16, 0.20, 0.18, 0.13, 0.08, 0.04, 0.02]

# Higher risk (weaker) grades priced at a higher rate — standard credit pricing logic.
BASE_RATE_BY_GRADE = {
    "AAA": 0.030, "AA": 0.035, "A": 0.042, "BBB": 0.050, "BB": 0.060,
    "B": 0.072, "CCC": 0.088, "CC": 0.105, "C": 0.125, "D": 0.150,
}

INDUSTRY_SECTORS = [
    "Consumer/Retail", "Manufacturing", "Healthcare", "Technology",
    "Real Estate", "Construction", "Agriculture", "Financial Services",
    "Hospitality", "Energy",
]
INDUSTRY_PROBS = [0.30, 0.10, 0.08, 0.08, 0.12, 0.08, 0.06, 0.08, 0.06, 0.04]

REGIONS = [
    "London", "South East", "South West", "East of England", "Midlands",
    "North West", "North East", "Yorkshire and the Humber", "Scotland",
    "Wales", "Northern Ireland",
]

COLLATERAL_TYPES = ["unsecured", "residential", "commercial", "other"]
COLLATERAL_PROBS = [0.35, 0.35, 0.20, 0.10]

TERM_MONTHS_CHOICES = [12, 24, 36, 60, 120, 180, 240, 300, 360]
TERM_MONTHS_PROBS = [0.10, 0.12, 0.15, 0.18, 0.12, 0.10, 0.10, 0.07, 0.06]

AMORT_TYPE_PROBS = {"reducing_balance": 0.85, "bullet": 0.15}


def generate_portfolio(n=N_LOANS, seed=SEED, reporting_date=REPORTING_DATE):
    rng = np.random.default_rng(seed)
    fake = Faker()
    Faker.seed(seed)

    loan_id = [f"L{str(i).zfill(6)}" for i in range(1, n + 1)]

    term_months = rng.choice(TERM_MONTHS_CHOICES, size=n, p=TERM_MONTHS_PROBS)

    # Origination must be recent enough that the loan is still active (not yet
    # matured) as of the reporting date — a "current" loan book shouldn't
    # contain loans that already finished. Bounded per-loan by that loan's own
    # term, capped at a 10-year lookback, with a 45-day buffer to stay clear
    # of maturity even after Phase 3's calendar-accurate schedule replaces
    # this file's 30-days/month approximation.
    days_back_max = np.clip(term_months.astype(int) * 30 - 45, 30, 3650)
    origination_date = pd.Series(pd.to_datetime([
        fake.date_between(
            start_date=(reporting_date - pd.Timedelta(days=int(days_back_max[i]))).date(),
            end_date=reporting_date.date(),
        )
        for i in range(n)
    ]))
    # 30 days/month approximation here; Phase 3's real schedule uses calendar months.
    maturity_date = origination_date + pd.to_timedelta(term_months.astype(int) * 30, unit="D")

    borrower_risk_grade = rng.choice(RISK_GRADES, size=n, p=RISK_GRADE_PROBS)

    # Lognormal so most loans are modest-sized with a realistic long tail of large ones.
    base_principal = rng.lognormal(mean=10.5, sigma=1.0, size=n)
    principal = np.round(np.clip(base_principal, 2_000, 3_000_000), -2)

    interest_rate = np.array([
        BASE_RATE_BY_GRADE[g] + rng.normal(0, 0.003) for g in borrower_risk_grade
    ])
    interest_rate = np.clip(interest_rate, 0.01, 0.20).round(4)

    amortisation_type = rng.choice(
        list(AMORT_TYPE_PROBS.keys()), size=n, p=list(AMORT_TYPE_PROBS.values())
    )

    industry_sector = rng.choice(INDUSTRY_SECTORS, size=n, p=INDUSTRY_PROBS)
    region = rng.choice(REGIONS, size=n)

    collateral_type = rng.choice(COLLATERAL_TYPES, size=n, p=COLLATERAL_PROBS)
    ltv = np.where(
        np.isin(collateral_type, ["residential", "commercial"]),
        np.clip(rng.normal(0.65, 0.15, size=n), 0.10, 0.95).round(4),
        np.nan,
    )

    elapsed_months = np.minimum(
        term_months,
        ((reporting_date - origination_date).dt.days / 30.44).astype(int),
    )
    frac_elapsed = np.where(term_months > 0, elapsed_months / term_months, 0)
    # Straight-line placeholder balance — Phase 3 replaces this with the real
    # reducing-balance amortisation schedule; bullet loans stay at full principal.
    current_balance = np.where(
        amortisation_type == "bullet",
        principal,
        principal * (1 - frac_elapsed),
    )
    current_balance = np.round(np.clip(current_balance, 0, None), 2)

    grade_rank = np.array([RISK_GRADES.index(g) for g in borrower_risk_grade])
    arrears_lambda = 1 + grade_rank * 3
    arrears_days = rng.poisson(arrears_lambda, size=n)
    distress_mask = rng.random(n) < (0.01 + 0.015 * grade_rank / len(RISK_GRADES))
    arrears_days = np.where(
        distress_mask, arrears_days + rng.integers(60, 200, size=n), arrears_days
    )
    arrears_days = np.clip(arrears_days, 0, None)

    status = np.select(
        [arrears_days >= 90, arrears_days >= 30],
        ["default", "watch"],
        default="performing",
    )

    return pd.DataFrame({
        "loan_id": loan_id,
        "origination_date": origination_date,
        "maturity_date": maturity_date,
        "term_months": term_months,
        "principal": principal,
        "interest_rate": interest_rate,
        "amortisation_type": amortisation_type,
        "borrower_risk_grade": borrower_risk_grade,
        "industry_sector": industry_sector,
        "region": region,
        "collateral_type": collateral_type,
        "ltv": ltv,
        "current_balance": current_balance,
        "arrears_days": arrears_days,
        "status": status,
    })


if __name__ == "__main__":
    portfolio = generate_portfolio()
    out_path = Path(__file__).resolve().parent / "loan_portfolio.parquet"
    portfolio.to_parquet(out_path, index=False)
    print(f"Generated {len(portfolio)} loans -> {out_path}")
    print(portfolio.head())
    print(portfolio["status"].value_counts())
