"""Primary Streamlit experience for Chargeback Sentinel."""
import uuid
import tempfile

import pandas as pd
import streamlit as st

from chargeback_risk_engine.config import REASON_CODES, RELEVANT_EVIDENCE_BY_REASON
from chargeback_risk_engine.local_pipeline import score_dispute_locally
from chargeback_risk_engine.metrics import (
    run_pipeline,
    confusion_matrix_for_auto_contest,
    precision_recall_f1,
    false_positive_cost,
    calibration_check,
)
from chargeback_risk_engine.baseline import run_naive_baseline
from chargeback_risk_engine.paths import DATA_DIR

st.set_page_config(page_title="Chargeback Sentinel", page_icon="🛡️", layout="wide")
st.title("Chargeback Sentinel")
st.caption("Evidence-first chargeback decisioning")
st.write("AI proposes. Evidence verifies. Economics prioritizes. Policy decides.")

score_tab, proof_tab = st.tabs(["Decision", "Proof"])

with score_tab:
    left, right = st.columns([1, 1.25])
    with left:
        reason_code = st.selectbox("Reason code", REASON_CODES)
        amount = st.number_input("Disputed amount (₹)", min_value=1.0, value=2400.0, step=100.0)
        if "current_dispute_id" not in st.session_state:
            st.session_state.current_dispute_id = f"D_DEMO_{uuid.uuid4().hex[:8].upper()}"
        dispute_id = st.text_input("Case ID", value=st.session_state.current_dispute_id)

        st.markdown("Evidence")
        evidence_values = {}
        for field in RELEVANT_EVIDENCE_BY_REASON[reason_code]:
            choice = st.radio(
                field.replace("_", " "),
                ["Yes", "No", "Unknown"],
                index=2,
                key=f"evidence_{field}",
                horizontal=True,
            )
            evidence_values[field] = {"Yes": True, "No": False, "Unknown": None}[choice]

        if st.button("Evaluate case", type="primary"):
            dispute = {
                "dispute_id": dispute_id,
                "payment_id": "pay_streamlit_demo",
                "reason_code": reason_code,
                "amount": amount,
                **evidence_values,
            }
            st.session_state.last_result = score_dispute_locally(dispute)

    with right:
        result = st.session_state.get("last_result")
        if result:
            if result["replayed"]:
                st.info("This case ID already has a persisted decision; the original decision is being replayed.")

            a, b, c = st.columns(3)
            a.metric("Model win-probability estimate", f"{result['win_probability']:.1%}")
            b.metric("Expected net value", f"₹{result['economic_decision']['expected_net_value']:,.0f}")
            c.metric("Decision", result["action"])

            st.markdown("### Why")
            explanation = result["explanation"]
            for reason in [
                explanation["policy_reason"],
                explanation["economic_reason"],
                explanation["graph_reason"],
            ]:
                st.write("•", reason)

            e1, e2, e3 = st.columns(3)
            e1.metric("Evidence completeness", f"{result['evidence_score']['completeness']:.0%}")
            e2.metric("Evidence validity", f"{result['evidence_score']['validity']:.0%}")
            e3.metric("Evidence confidence", f"{result['evidence_score']['confidence']:.0%}")

            st.markdown("### Evidence")
            st.dataframe(pd.DataFrame(result["evidence"]), hide_index=True, use_container_width=True)

            st.markdown("### What would change the decision?")
            st.write(result["counterfactual"]["statement"])

            with st.expander("Economics"):
                st.json(result["economic_decision"])
            with st.expander("Audit"):
                st.write(f"Audit ID: `{result['audit_id']}`")
                st.write(f"Model: `{result['model_version']}` · Policy: `{result['policy_version']}` · Features: `{result['feature_version']}`")
            if result.get("contest_draft"):
                with st.expander("Contest draft"):
                    st.caption("Draft only. This system does not submit external financial actions.")
                    st.json(result["contest_draft"])
        else:
            st.info("Enter a case, select evidence, and evaluate it to see the full decision path.")

with proof_tab:
    st.subheader("Held-out evaluation")
    st.caption("Synthetic benchmark data only; these figures are not production performance claims.")
    test = pd.read_csv(DATA_DIR / "test.csv")
    with tempfile.TemporaryDirectory(prefix="sentinel_ui_eval_") as tmp:
        results = run_pipeline(test, db_path=f"{tmp}/evaluation_audit.db")
    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)
    naive = run_naive_baseline(test)
    proof_df = pd.DataFrame({
        "Metric": ["Auto-contest precision", "Auto-contest recall", "Auto-contest F1", "False-positive contest cost (₹)", "Human-review rate"],
        "Chargeback Sentinel": [prf["precision"], prf["recall"], prf["f1"], false_positive_cost(results), (results["action"] == "HUMAN-REVIEW").mean()],
        "Always contest": [naive["precision"], naive["recall"], naive["f1"], naive["false_positive_cost"], 0.0],
    })
    st.dataframe(proof_df, hide_index=True, use_container_width=True)
    st.markdown("### Calibration check")
    st.dataframe(calibration_check(results), hide_index=True, use_container_width=True)
    st.markdown("### Auditability")
    st.write("The benchmark calls the same canonical decision service as the API and local case screen. HGB and rules are challengers, not live decision paths.")
