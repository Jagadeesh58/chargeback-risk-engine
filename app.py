"""
app.py — Streamlit frontend. Contains ZERO scoring/policy business logic
of its own for the "Score a Dispute" tab -- it calls the FastAPI backend
(api.py) exactly like any other HTTP client would. The dashboard tab
reuses the already-tested metrics.py/baseline.py/sensitivity.py modules
directly (same tested code, not reimplemented) to visualize results
that were already measured elsewhere.
"""

import uuid

import pandas as pd
import requests
import streamlit as st
import altair as alt

from config import RELEVANT_EVIDENCE_BY_REASON, REASON_CODES
from metrics import run_pipeline, confusion_matrix_for_auto_contest, precision_recall_f1, false_positive_cost, calibration_check
from baseline import run_naive_baseline
from sensitivity import sweep_auto_contest_threshold
from calibration import fit_calibration_points, calibration_error

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Chargeback Risk Engine", layout="wide")
st.title("Chargeback Risk Engine")

tab1, tab2 = st.tabs(["Score a Dispute", "Model Performance Dashboard"])

# ============================================================
# TAB 1: Score a Dispute -- calls the real API, no logic here
# ============================================================
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
        payload = {
            "dispute_id": dispute_id,
            "payment_id": "pay_streamlit_demo",
            "reason_code": reason_code,
            "amount": amount,
            **evidence_values,
        }
        try:
            response = requests.post(f"{API_URL}/score", json=payload, timeout=5)
            response.raise_for_status()
            result = response.json()

            st.divider()
            action_color = {
                "AUTO-CONTEST": "green",
                "HUMAN REVIEW": "orange",
                "ACCEPT LOSS": "red",
            }.get(result["action"], "gray")

            colA, colB, colC, colD = st.columns(4)
            colA.metric("Win Probability (raw)", f"{result['win_probability']:.1%}")
            colB.metric("Calibrated", f"{result['calibrated_win_probability']:.1%}")
            colC.markdown(f"### :{action_color}[{result['action']}]")
            colD.metric("Expected Value", f"Rs {result['expected_value']:,.2f}")
            st.caption(
                "The decision above was made from the raw probability, not the calibrated "
                "one -- calibration only corrects the number for a human to read."
            )

            st.markdown(f"**Reason:** {result['reason']}")

            st.markdown("**Evidence packet:**")
            evidence_df = pd.DataFrame(result["evidence"])
            st.dataframe(evidence_df, hide_index=True, use_container_width=True)

            if result.get("contest_draft"):
                with st.expander("Contest draft (Razorpay evidence-submission shape)"):
                    st.caption(
                        "Auto-generated because the decision was AUTO-CONTEST. "
                        "Always action=\"draft\" -- nothing in this system ever submits it."
                    )
                    st.json(result["contest_draft"])

        except requests.exceptions.ConnectionError:
            st.error(
                "Could not connect to the API. Make sure it's running: "
                "`uvicorn api:app --reload` in another terminal."
            )

# ============================================================
# TAB 2: Model Performance Dashboard -- reuses tested modules directly
# ============================================================
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

        calib_points = fit_calibration_points("dev.csv")
        pairs = list(zip(results["p_win"], results["would_win"].astype(float)))
        raw_error = calibration_error(pairs, points=None)
        calibrated_err = calibration_error(pairs, points=calib_points)
        colX, colY = st.columns(2)
        colX.metric("Calibration error (raw scorer)", f"{raw_error:.4f}")
        colY.metric("After isotonic calibration (fit on dev.csv)", f"{calibrated_err:.4f}")
        st.caption(
            "Isotonic regression fit on dev.csv, measured here on the held-out test set. "
            "Not used to decide AUTO-CONTEST / HUMAN REVIEW / ACCEPT LOSS -- that decision "
            "still uses the raw score it was fuzz-tested against; this is a separate, more "
            "honest probability for a human reviewing the case."
        )

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