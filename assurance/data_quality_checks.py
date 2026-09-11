"""Phase 6 — data quality checks.

Runs a set of independent integrity checks against the portfolio and its
derived files: null/completeness checks, duplicate keys, out-of-range
values, categorical validity, and orphan-record checks between files that
should reference each other consistently. This is the automated first
line of the data-assurance layer — see assurance/model_validation_memo.md
for how these results are interpreted.

Run from the assure/ folder: `python assurance/data_quality_checks.py`
Writes assurance/data_quality_results.json.
"""

import json
from pathlib import Path

import pandas as pd

VALID_RISK_GRADES = {"AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "C", "D"}
VALID_COLLATERAL_TYPES = {"unsecured", "residential", "commercial", "other"}
VALID_AMORT_TYPES = {"reducing_balance", "bullet"}
VALID_STATUSES = {"performing", "watch", "default"}


def _check(name, description, violation_ids, checked_count):
    n = len(violation_ids)
    return {
        "check": name,
        "description": description,
        "records_checked": int(checked_count),
        "violations_found": int(n),
        "status": "PASS" if n == 0 else "FAIL",
        "sample_violation_ids": list(violation_ids[:10]),
    }


def check_duplicates(portfolio: pd.DataFrame) -> dict:
    dupes = portfolio.loc[portfolio["loan_id"].duplicated(keep=False), "loan_id"].unique().tolist()
    return _check(
        "duplicate_loan_ids",
        "Every loan_id should be unique — a duplicate would double-count exposure.",
        dupes, len(portfolio),
    )


def check_required_nulls(portfolio: pd.DataFrame) -> dict:
    # ltv is deliberately null for unsecured/other loans (see docs/methodology.md) —
    # every other field is required, so nulls there are a genuine finding.
    required_cols = [c for c in portfolio.columns if c != "ltv"]
    null_mask = portfolio[required_cols].isna().any(axis=1)
    bad_ids = portfolio.loc[null_mask, "loan_id"].tolist()
    return _check(
        "unexpected_nulls",
        "No nulls expected in any field except ltv (which is null by design for "
        "unsecured/other collateral).",
        bad_ids, len(portfolio),
    )


def check_ltv_null_pattern(portfolio: pd.DataFrame) -> dict:
    should_have_ltv = portfolio["collateral_type"].isin(["residential", "commercial"])
    mismatch = should_have_ltv & portfolio["ltv"].isna()
    mismatch |= (~should_have_ltv) & portfolio["ltv"].notna()
    bad_ids = portfolio.loc[mismatch, "loan_id"].tolist()
    return _check(
        "ltv_null_pattern",
        "ltv should be populated only for residential/commercial collateral, and "
        "null otherwise.",
        bad_ids, len(portfolio),
    )


def check_out_of_range(portfolio: pd.DataFrame) -> dict:
    violations = pd.Series(False, index=portfolio.index)
    violations |= portfolio["principal"] <= 0
    violations |= portfolio["current_balance"] < 0
    violations |= portfolio["current_balance"] > portfolio["principal"] + 0.01
    violations |= portfolio["interest_rate"] < 0
    violations |= portfolio["interest_rate"] > 0.5
    violations |= portfolio["term_months"] <= 0
    violations |= portfolio["arrears_days"] < 0
    violations |= portfolio["ltv"] > 1.0
    violations |= portfolio["ltv"] < 0
    violations |= portfolio["maturity_date"] <= portfolio["origination_date"]
    bad_ids = portfolio.loc[violations, "loan_id"].tolist()
    return _check(
        "out_of_range_values",
        "principal>0, 0<=current_balance<=principal, 0<=interest_rate<=50%, "
        "term_months>0, arrears_days>=0, 0<=ltv<=100%, maturity_date>origination_date.",
        bad_ids, len(portfolio),
    )


def check_categorical_validity(portfolio: pd.DataFrame) -> dict:
    violations = pd.Series(False, index=portfolio.index)
    violations |= ~portfolio["borrower_risk_grade"].isin(VALID_RISK_GRADES)
    violations |= ~portfolio["collateral_type"].isin(VALID_COLLATERAL_TYPES)
    violations |= ~portfolio["amortisation_type"].isin(VALID_AMORT_TYPES)
    violations |= ~portfolio["status"].isin(VALID_STATUSES)
    bad_ids = portfolio.loc[violations, "loan_id"].tolist()
    return _check(
        "categorical_validity",
        "borrower_risk_grade/collateral_type/amortisation_type/status must be one of "
        "their defined allowed values.",
        bad_ids, len(portfolio),
    )


def check_active_as_of_reporting_date(portfolio: pd.DataFrame, reporting_date) -> dict:
    reporting_date = pd.Timestamp(reporting_date)
    matured = portfolio.loc[portfolio["maturity_date"] <= reporting_date, "loan_id"].tolist()
    return _check(
        "no_matured_loans_in_book",
        "Every loan in a 'current' portfolio snapshot should still be active "
        "(maturity_date > reporting_date) — this check caught a real Phase 2 bug, see "
        "docs/methodology.md.",
        matured, len(portfolio),
    )


def check_orphan_schedule_rows(portfolio: pd.DataFrame, schedules: pd.DataFrame) -> dict:
    orphans = schedules.loc[~schedules["loan_id"].isin(portfolio["loan_id"]), "loan_id"].unique().tolist()
    return _check(
        "orphan_schedule_rows",
        "Every loan_id in amortisation_schedules.parquet should exist in "
        "loan_portfolio.parquet.",
        orphans, schedules["loan_id"].nunique(),
    )


def check_portfolio_loans_have_schedules(portfolio: pd.DataFrame, schedules: pd.DataFrame) -> dict:
    missing = portfolio.loc[~portfolio["loan_id"].isin(schedules["loan_id"]), "loan_id"].tolist()
    return _check(
        "portfolio_loans_missing_schedule",
        "Every loan in loan_portfolio.parquet should have at least one row in "
        "amortisation_schedules.parquet.",
        missing, len(portfolio),
    )


def check_orphan_ecl_rows(portfolio: pd.DataFrame, ecl_results: pd.DataFrame) -> dict:
    orphans = ecl_results.loc[~ecl_results["loan_id"].isin(portfolio["loan_id"]), "loan_id"].tolist()
    missing = portfolio.loc[~portfolio["loan_id"].isin(ecl_results["loan_id"]), "loan_id"].tolist()
    bad_ids = orphans + missing
    return _check(
        "ecl_results_loan_id_match",
        "loan_portfolio.parquet and ecl_results.parquet should contain exactly the "
        "same set of loan_ids.",
        bad_ids, len(portfolio),
    )


def run_all_checks(portfolio, schedules, ecl_results, reporting_date) -> list:
    return [
        check_duplicates(portfolio),
        check_required_nulls(portfolio),
        check_ltv_null_pattern(portfolio),
        check_out_of_range(portfolio),
        check_categorical_validity(portfolio),
        check_active_as_of_reporting_date(portfolio, reporting_date),
        check_orphan_schedule_rows(portfolio, schedules),
        check_portfolio_loans_have_schedules(portfolio, schedules),
        check_orphan_ecl_rows(portfolio, ecl_results),
    ]


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")
    schedules = pd.read_parquet(base / "data" / "amortisation_schedules.parquet")
    ecl_results = pd.read_parquet(base / "data" / "ecl_results.parquet")
    REPORTING_DATE = pd.Timestamp("2025-12-31")

    results = run_all_checks(portfolio, schedules, ecl_results, REPORTING_DATE)

    out_path = Path(__file__).resolve().parent / "data_quality_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))

    passed = sum(1 for r in results if r["status"] == "PASS")
    print(f"Data quality checks: {passed}/{len(results)} passed\n")
    for r in results:
        print(f"[{r['status']}] {r['check']} — {r['violations_found']} violation(s) "
              f"of {r['records_checked']} checked")
    print(f"\nFull results -> {out_path}")
