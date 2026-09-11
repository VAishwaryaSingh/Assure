"""Phase 5 — macro scenario engine.

Re-runs the Phase 4 ECL calculation three times under different macro
assumptions, by scaling every risk grade's PD up (worse economy -> higher
chance of default), then combines the three results into a single
probability-weighted ECL — the "different outcomes under different
assumptions, with a recommended view" business-case output plan.md asks
for (Section 5, Phase 5).

Run from the assure/ folder: `python model/scenarios.py`
"""

from pathlib import Path

import pandas as pd

from ecl import PD_12M_BY_GRADE, calculate_ecl

# PD multipliers: plan.md Section 5 suggests these exact example values
# (adverse = 1.5x base PD, severe = 2.5x). Scenario *probabilities* are this
# project's own assumption — base-case-most-likely weighting is a common
# convention in multi-scenario IFRS 9 ECL, not a calibrated forecast.
# Both are disclosed, not hidden — see docs/methodology.md.
SCENARIOS = {
    "base":    {"pd_multiplier": 1.0, "probability": 0.60},
    "adverse": {"pd_multiplier": 1.5, "probability": 0.30},
    "severe":  {"pd_multiplier": 2.5, "probability": 0.10},
}


def scaled_pd_table(multiplier: float, base_table: dict = PD_12M_BY_GRADE) -> dict:
    """Scales every grade's PD, capped at 100% (a probability can't exceed 1)."""
    return {grade: min(pd_val * multiplier, 1.0) for grade, pd_val in base_table.items()}


def run_all_scenarios(portfolio: pd.DataFrame, schedules: pd.DataFrame, as_of_date) -> dict:
    """Returns {scenario_name: per-loan result DataFrame} for all three scenarios."""
    results = {}
    for name, cfg in SCENARIOS.items():
        pd_table = scaled_pd_table(cfg["pd_multiplier"])
        results[name] = calculate_ecl(portfolio, schedules, as_of_date, pd_table)
    return results


def weighted_ecl(results: dict) -> float:
    """Probability-weighted total ECL across all scenarios."""
    return sum(
        results[name]["ecl"].sum() * SCENARIOS[name]["probability"] for name in results
    )


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")
    schedules = pd.read_parquet(base / "data" / "amortisation_schedules.parquet")
    REPORTING_DATE = pd.Timestamp("2025-12-31")

    results = run_all_scenarios(portfolio, schedules, REPORTING_DATE)

    combined = pd.concat(
        [df.assign(scenario=name) for name, df in results.items()], ignore_index=True
    )
    out_path = base / "data" / "ecl_scenarios.parquet"
    combined.to_parquet(out_path, index=False)
    print(f"Calculated ECL for {len(SCENARIOS)} scenarios -> {out_path}")

    print("\nScenario summary:")
    summary_rows = []
    for name, cfg in SCENARIOS.items():
        total_ecl = results[name]["ecl"].sum()
        exposure = results[name]["current_balance"].sum()
        summary_rows.append({
            "scenario": name,
            "pd_multiplier": cfg["pd_multiplier"],
            "probability": cfg["probability"],
            "total_ecl": round(total_ecl, 2),
            "coverage_%": round(total_ecl / exposure * 100, 3),
        })
    summary = pd.DataFrame(summary_rows).set_index("scenario")
    print(summary)

    w_ecl = weighted_ecl(results)
    print(f"\nProbability-weighted ECL: {w_ecl:,.2f}")
    print(f"vs. base-case-only ECL:   {results['base']['ecl'].sum():,.2f}")
    print(f"Uplift over base case:    {w_ecl - results['base']['ecl'].sum():,.2f} "
          f"({(w_ecl / results['base']['ecl'].sum() - 1) * 100:.1f}%)")
