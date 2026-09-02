"""
app_deployed.py — self-contained version of the Streamlit frontend, for
public deployment (e.g. Streamlit Community Cloud) where a separate
FastAPI server isn't available.

IMPORTANT: this does NOT duplicate any business logic. It calls
scorer.py / evidence.py / policy.py / audit_log.py directly -- the
exact same tested functions api.py calls over HTTP. The only difference
from app.py is HOW the pipeline is reached (direct function call here,
vs. an HTTP request in app.py) -- never WHAT the pipeline does.

For local development, prefer app.py + a running api.py, since that
exercises the real HTTP layer end-to-end. This file exists specifically
so a panelist can click one public link and have everything work with
zero setup on their end.
"""

import uuid

import pandas as pd
import streamlit as st
import altair as alt

from config import RELEVANT_EVIDENCE_BY_REASON, REASON_CODES
from local_pipeline import score_dispute_locally
from metrics import run_pipeline, confusion_matrix_for_auto_contest, precision_recall_f1, false_positive_cost, calibration_check
from baseline import run_naive_baseline
from sensitivity import sweep_auto_contest_threshold


st.set_page_config(page_title="Chargeback Risk Engine", layout="wide")
st.title("Chargeback Risk Engine")
st.caption(
    "Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager. "
    "This public demo calls the same tested scorer/evidence/policy pipeline "
    "directly (no separate API server needed for this deployed version) — "
    "see api.py in the repo for the full REST API + audit trail."
)

tab1, tab2 = st.tabs(["Score a Dispute", "Model Performance Dashboard"])

with tab1:
    st.subheader("Score a single dispute")

    col1, col2 = st.columns(2)
    with col1:
        reason_code = st.selectbox("Reason code", REASON_CODES)
        amount = st.number_input("Disputed amount (Rs)", min_value=0.0, value=2000.0, step=100.0)

        if "current_dispute_id" not in st.session_state:
            st.session_state.current_dispute_id = f"D_DEMO_{uuid.uuid4().hex[:8].upper()}"

        dispute_id = st.text_input("Dispute ID", value=st.session_state.current_dispute_id, key="dispute_id_input")

    st.markdown(f"**Evidence for `{reason_code}`:**")
    relevant_fields = RELEVANT_EVIDENCE_BY_REASON[reason_code]
    evidence_values = {}
    cols = st.columns(len(relevant_fields))
    for col, field in zip(cols, relevant_fields):
        with col:
            choice = st.radio(
                field.replace("_", " "),
                options=["Yes", "No", "Unknown"],
                index=2,
                key=field,
            )
            evidence_values[field] = {"Yes": True, "No": False, "Unknown": None}[choice]

    if st.button("Score Dispute", type="primary"):
        dispute = {
            "dispute_id": dispute_id,
            "reason_code": reason_code,
            "amount": amount,
            **evidence_values,
        }
        result = score_dispute_locally(dispute)

        st.divider()
        if result["replayed"]:
            st.info(f"This dispute_id was already scored before — showing the original decision (idempotent replay).")

        action_color = {
            "AUTO-CONTEST": "green",
            "HUMAN REVIEW": "orange",
            "ACCEPT LOSS": "red",
        }.get(result["action"], "gray")

        colA, colB, colC = st.columns(3)
        colA.metric("Win Probability", f"{result['win_probability']:.1%}")
        colB.markdown(f"### :{action_color}[{result['action']}]")
        colC.metric("Expected Value", f"Rs {result['expected_value']:,.2f}")

        st.markdown(f"**Reason:** {result['reason']}")

        st.markdown("**Evidence packet:**")
        evidence_df = pd.DataFrame(result["evidence"])
        st.dataframe(evidence_df, hide_index=True, use_container_width=True)

with tab2:
    st.subheader("Performance on held-out test set (900 disputes)")
    st.caption(
        "All numbers below are measured inside our synthetic evaluation "
        "environment — not a claim about real-world chargeback accuracy."
    )

    test = pd.read_csv("test.csv")
    results = run_pipeline(test)
    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)
    fp_cost = false_positive_cost(results)
    naive = run_naive_baseline(test)

    st.markdown("### Real pipeline vs. naive 'contest everything' baseline")
    comparison_df = pd.DataFrame({
        "Metric": ["Precision", "Recall", "F1", "False-positive cost (Rs)"],
        "Naive baseline": [naive["precision"], naive["recall"], naive["f1"], naive["false_positive_cost"]],
        "Real pipeline": [prf["precision"], prf["recall"], prf["f1"], fp_cost],
    })
    st.dataframe(comparison_df, hide_index=True, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Calibration check")
        calibration = calibration_check(results, n_bins=5)
        calibration_plot_df = pd.melt(
            calibration.reset_index(),
            id_vars=["bin"],
            value_vars=["avg_predicted", "actual_win_rate"],
            var_name="type",
            value_name="rate",
        )
        chart = alt.Chart(calibration_plot_df).mark_line(point=True).encode(
            x=alt.X("bin:N", title="Predicted probability bin"),
            y=alt.Y("rate:Q", title="Rate"),
            color="type:N",
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption("Predicted vs actual win rate per bin. A perfectly calibrated scorer would have the two lines overlap.")

    with col2:
        st.markdown("### Threshold sensitivity")
        thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
        sweep = sweep_auto_contest_threshold(test, thresholds)
        sweep_plot_df = pd.melt(
            sweep, id_vars=["threshold"], value_vars=["precision", "recall"],
            var_name="metric", value_name="value",
        )
        chart2 = alt.Chart(sweep_plot_df).mark_line(point=True).encode(
            x=alt.X("threshold:Q", title="AUTO_CONTEST_THRESHOLD"),
            y=alt.Y("value:Q", title="Score"),
            color="metric:N",
        )
        st.altair_chart(chart2, use_container_width=True)
        st.caption("Precision/recall tradeoff as the auto-contest threshold changes.")