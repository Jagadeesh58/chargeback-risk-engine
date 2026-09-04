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

from chargeback_risk_engine.config import RELEVANT_EVIDENCE_BY_REASON, REASON_CODES
from chargeback_risk_engine.local_pipeline import score_dispute_locally
from chargeback_risk_engine.metrics import run_pipeline, confusion_matrix_for_auto_contest, precision_recall_f1, false_positive_cost, calibration_check
from chargeback_risk_engine.baseline import run_naive_baseline
from chargeback_risk_engine.sensitivity import sweep_auto_contest_threshold
from chargeback_risk_engine.calibration import fit_calibration_points, calibration_error
from chargeback_risk_engine.paths import DATA_DIR

st.set_page_config(page_title="Chargeback Risk Engine", layout="wide")
st.title("Chargeback Risk Engine")
st.caption("Razorpay AI Buildathon 2026")

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

        colA, colB, colC, colD, colE = st.columns(5)
        colA.metric("Rule Risk", f"{result['win_probability']:.1%}")
        colB.metric("Calibrated", f"{result['calibrated_win_probability']:.1%}")
        colC.metric("Logistic ML", f"{result['ml_win_probability']:.1%}")
        colD.metric("Tree ML", f"{result.get('tree_model_probability', 0.0):.1%}")
        colE.markdown(f"### :{action_color}[{result['action']}]")
        st.metric("Expected Net Value", f"Rs {result['economic_decision']['expected_net_value']:,.2f}")
        st.caption(
            "AI outputs are advisory signals. The final action remains deterministic policy "
            "with evidence, economic and safety gates; the tree model is an independent comparison signal."
        )
        ec1, ec2, ec3 = st.columns(3)
        ec1.metric("Evidence completeness", f"{result['evidence_score']['completeness']:.1%}")
        ec2.metric("Evidence validity", f"{result['evidence_score']['validity']:.1%}")
        ec3.metric("Evidence confidence", f"{result['evidence_score']['confidence']:.1%}")

        with st.expander("Why did the system choose this action?", expanded=True):
            st.write(result["explanation"]["policy_reason"])
            st.write(result["explanation"]["economic_reason"])
            st.write("Supporting evidence:", result["explanation"]["supporting_evidence"] or "None")
            st.write("Missing or non-PASS evidence:", result["explanation"]["missing_evidence"] or "None")
            st.write("Graph signal:", result["explanation"]["graph_reason"])
            st.write("Safety:", "; ".join(result["explanation"]["safety_notes"]))

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

        st.markdown("**Decision lineage:**")
        st.caption(f"model={result['model_version']} · rule={result['rule_model_version']} · features={result['feature_version']} · policy={result['policy_version']}")
        if result["graph_analysis"]["suspicious_clusters"]:
            st.warning(result["graph_analysis"]["explanation"])

with tab2:
    st.subheader("Performance on held-out test set (900 disputes)")
    st.caption(
        "All numbers below are measured inside our synthetic evaluation "
        "environment — not a claim about real-world chargeback accuracy."
    )

    test = pd.read_csv(DATA_DIR / "test.csv")
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

        calib_points = fit_calibration_points(str(DATA_DIR / "dev.csv"))
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