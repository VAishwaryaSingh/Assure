"""Phase 6 — PD/LGD sensitivity testing.

Not one of the files in plan.md's original assurance/ layout — added
because the Model Validation Memo (plan.md Section 7, point 6) explicitly
calls for sensitivity results, and this reuses the exact same PD/LGD-table
swapping mechanism built for the Phase 5 scenario engine (model/ecl.py's
calculate_ecl), rather than duplicating any calculation logic.

Flexes PD and LGD independently by +/-10% and +/-20% (holding the other
factor at its base-case value) and reports the resulting total ECL.

Run from the assure/ folder: `python assurance/sensitivity_analysis.py`
Writes assurance/sensitivity_results.json.
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "model"))
from ecl import PD_12M_BY_GRADE, LGD_BY_COLLATERAL, calculate_ecl  # noqa: E402

REPORTING_DATE = pd.Timestamp("2025-12-31")
SHOCKS = [-0.20, -0.10, 0.0, 0.10, 0.20]


def scale_table(table: dict, shock: float) -> dict:
    return {k: min(v * (1 + shock), 1.0) for k, v in table.items()}


def run_sensitivity(portfolio: pd.DataFrame, schedules: pd.DataFrame) -> list:
    base_result = calculate_ecl(portfolio, schedules, REPORTING_DATE)
    base_ecl = base_result["ecl"].sum()

    rows = []
    for shock in SHOCKS:
        pd_table = scale_table(PD_12M_BY_GRADE, shock)
        result = calculate_ecl(portfolio, schedules, REPORTING_DATE, pd_table=pd_table)
        ecl = result["ecl"].sum()
        rows.append({
            "factor": "PD", "shock_%": round(shock * 100, 0),
            "total_ecl": round(ecl, 2),
            "change_vs_base_%": round((ecl / base_ecl - 1) * 100, 2),
        })

    for shock in SHOCKS:
        lgd_table = scale_table(LGD_BY_COLLATERAL, shock)
        result = calculate_ecl(portfolio, schedules, REPORTING_DATE, lgd_table=lgd_table)
        ecl = result["ecl"].sum()
        rows.append({
            "factor": "LGD", "shock_%": round(shock * 100, 0),
            "total_ecl": round(ecl, 2),
            "change_vs_base_%": round((ecl / base_ecl - 1) * 100, 2),
        })

    return rows


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    portfolio = pd.read_parquet(base / "data" / "loan_portfolio.parquet")
    schedules = pd.read_parquet(base / "data" / "amortisation_schedules.parquet")

    rows = run_sensitivity(portfolio, schedules)
    results = pd.DataFrame(rows)

    out_path = Path(__file__).resolve().parent / "sensitivity_results.json"
    out_path.write_text(json.dumps(rows, indent=2))

    print("PD sensitivity (LGD held at base case):")
    print(results[results["factor"] == "PD"].to_string(index=False))
    print("\nLGD sensitivity (PD held at base case):")
    print(results[results["factor"] == "LGD"].to_string(index=False))
    print(f"\nFull results -> {out_path}")
