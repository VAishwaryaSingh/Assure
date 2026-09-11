"""Phase 7 — Streamlit dashboard.

Pulls together every phase's output into one app: portfolio overview,
scenario comparison, a sector x risk-grade heatmap, and a data-quality /
assurance panel that surfaces the Phase 6 checks directly rather than
hiding them away.

Run from the assure/ folder: `streamlit run app/dashboard.py`
"""

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
ASSURANCE = BASE / "assurance"
REPORTING_DATE = "31 Dec 2025"
STAGE_LABELS = {1: "Stage 1 — Performing", 2: "Stage 2 — Watch", 3: "Stage 3 — Default"}
GRADE_ORDER = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "C", "D"]
SCENARIO_ORDER = ["base", "adverse", "severe"]
SCENARIO_PROBABILITIES = {"base": 0.60, "adverse": 0.30, "severe": 0.10}

st.set_page_config(page_title="Assure — Loan Portfolio ECL Dashboard", layout="wide")


@st.cache_data
def load_data():
    return {
        "ecl_results": pd.read_parquet(DATA / "ecl_results.parquet"),
        "ecl_scenarios": pd.read_parquet(DATA / "ecl_scenarios.parquet"),
        "dq_results": json.loads((ASSURANCE / "data_quality_results.json").read_text()),
        "recalc_results": pd.read_csv(ASSURANCE / "recalculation_test_results.csv"),
        "reconciliation": json.loads((ASSURANCE / "reconciliation_results.json").read_text()),
        "sensitivity": json.loads((ASSURANCE / "sensitivity_results.json").read_text()),
    }


data = load_data()
ecl_results = data["ecl_results"]
ecl_scenarios = data["ecl_scenarios"]

st.title("Assure — Loan Portfolio ECL Dashboard")
st.caption(
    f"Synthetic bank loan portfolio · IFRS 9 expected credit loss model · "
    f"reporting date {REPORTING_DATE} · all data is synthetic, see docs/methodology.md"
)

tab_overview, tab_scenarios, tab_heatmap, tab_dq = st.tabs(
    ["Portfolio Overview", "Scenarios & Sensitivity", "Risk Heatmap", "Data Quality & Assurance"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
    total_exposure = ecl_results["current_balance"].sum()
    total_ecl = ecl_results["ecl"].sum()
    coverage = total_ecl / total_exposure * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total loans", f"{len(ecl_results):,}")
    c2.metric("Total exposure", f"£{total_exposure:,.0f}")
    c3.metric("Total ECL", f"£{total_ecl:,.0f}")
    c4.metric("Coverage ratio", f"{coverage:.2f}%")

    st.subheader("Staging breakdown")
    stage_summary = (
        ecl_results.groupby("ifrs9_stage")
        .agg(loans=("loan_id", "count"), exposure=("current_balance", "sum"), ecl=("ecl", "sum"))
        .reset_index()
    )
    stage_summary["stage"] = stage_summary["ifrs9_stage"].map(STAGE_LABELS)
    stage_summary["coverage_%"] = (stage_summary["ecl"] / stage_summary["exposure"] * 100).round(2)

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            px.bar(stage_summary, x="stage", y="exposure", title="Exposure by stage",
                   labels={"exposure": "Exposure (£)", "stage": ""}),
            width="stretch",
        )
    with col2:
        st.plotly_chart(
            px.bar(stage_summary, x="stage", y="ecl", title="ECL by stage",
                   labels={"ecl": "ECL (£)", "stage": ""}),
            width="stretch",
        )

    st.dataframe(
        stage_summary[["stage", "loans", "exposure", "ecl", "coverage_%"]],
        width="stretch", hide_index=True,
    )

# ------------------------------------------------------- Scenarios & sensitivity
with tab_scenarios:
    st.subheader("ECL under each macro scenario")
    scenario_summary = (
        ecl_scenarios.groupby("scenario")
        .agg(exposure=("current_balance", "sum"), ecl=("ecl", "sum"))
        .reindex(SCENARIO_ORDER)
        .reset_index()
    )
    scenario_summary["coverage_%"] = (scenario_summary["ecl"] / scenario_summary["exposure"] * 100).round(3)
    scenario_summary["probability"] = scenario_summary["scenario"].map(SCENARIO_PROBABILITIES)

    weighted_ecl = (scenario_summary["ecl"] * scenario_summary["probability"]).sum()
    base_ecl = scenario_summary.loc[scenario_summary["scenario"] == "base", "ecl"].iloc[0]

    col1, col2 = st.columns([2, 1])
    with col1:
        st.plotly_chart(
            px.bar(scenario_summary, x="scenario", y="ecl", title="Total ECL by scenario",
                   labels={"ecl": "Total ECL (£)", "scenario": ""}, text_auto=".2s"),
            width="stretch",
        )
    with col2:
        st.metric("Probability-weighted ECL", f"£{weighted_ecl:,.0f}")
        st.metric("Uplift over base case", f"{(weighted_ecl / base_ecl - 1) * 100:.1f}%")
        st.caption("Weights: base 60% / adverse 30% / severe 10% — a disclosed "
                   "assumption, not a forecast. See docs/methodology.md.")

    st.dataframe(scenario_summary, width="stretch", hide_index=True)

    st.subheader("Sensitivity: PD / LGD flexed ±10% / ±20%")
    sens_df = pd.DataFrame(data["sensitivity"])
    st.plotly_chart(
        px.line(sens_df, x="shock_%", y="total_ecl", color="factor", markers=True,
                title="Total ECL vs. PD/LGD shock",
                labels={"shock_%": "Shock (%)", "total_ecl": "Total ECL (£)", "factor": "Factor"}),
        width="stretch",
    )
    st.caption("LGD sensitivity is exactly linear; PD sensitivity is sub-linear because "
               "Stage 3 loss (LGD × EAD) has no PD term — see docs/methodology.md.")

# ----------------------------------------------------------------- Heatmap
with tab_heatmap:
    st.subheader("Exposure concentration — sector × risk grade")
    heat_data = (
        ecl_results.pivot_table(
            index="industry_sector", columns="borrower_risk_grade",
            values="current_balance", aggfunc="sum", fill_value=0,
        )
        .reindex(columns=GRADE_ORDER, fill_value=0)
    )
    st.plotly_chart(
        px.imshow(
            heat_data, labels=dict(x="Risk grade", y="Sector", color="Exposure (£)"),
            aspect="auto", color_continuous_scale="Reds",
        ),
        width="stretch",
    )
    st.caption("Darker = larger exposure concentration in that sector/grade combination.")

# ---------------------------------------------------------- Data quality & assurance
with tab_dq:
    st.subheader("Data quality checks")
    dq_df = pd.DataFrame(data["dq_results"])
    passed = (dq_df["status"] == "PASS").sum()
    st.metric("Checks passed", f"{passed}/{len(dq_df)}")
    st.dataframe(
        dq_df[["check", "description", "records_checked", "violations_found", "status"]],
        width="stretch", hide_index=True,
    )

    st.subheader("Recalculation test — independent test of detail")
    recalc_df = data["recalc_results"]
    c1, c2 = st.columns(2)
    c1.metric("Balance recompute matches", f"{recalc_df['balance_match'].sum()}/{len(recalc_df)}")
    c2.metric("ECL recompute matches", f"{recalc_df['ecl_match'].sum()}/{len(recalc_df)}")
    st.caption("25 loans, independently recalculated from the documented formulas rather "
               "than by calling the production code — see assurance/recalculation_test.py.")
    st.dataframe(recalc_df, width="stretch", hide_index=True)

    st.subheader("Reconciliation")
    for check in data["reconciliation"]:
        st.write(f"**{check['check']}** — {check['status']}")
        st.json(check, expanded=False)

    st.info("Full written review, including limitations and a sign-off verdict: "
            "see assurance/model_validation_memo.md")

st.divider()
st.caption(
    "All figures are from a synthetic, illustrative portfolio — not a real bank's data. "
    "Full methodology and every disclosed assumption: docs/methodology.md."
)
