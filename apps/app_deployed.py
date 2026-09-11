"""Primary Streamlit experience for Chargeback Risk Engine."""

import json
import tempfile
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from chargeback_risk_engine.audit_log import verify_audit_integrity
from chargeback_risk_engine.config import REASON_CODES, RELEVANT_EVIDENCE_BY_REASON
from chargeback_risk_engine.local_pipeline import score_dispute_locally
from chargeback_risk_engine.engine.hybrid_pipeline import decide_case
from chargeback_risk_engine.engine.risk_graph import RiskGraph
from chargeback_risk_engine.metrics import (
    confusion_matrix_for_auto_contest,
    false_positive_cost,
    precision_recall_f1,
    run_pipeline,
)
from chargeback_risk_engine.paths import DATA_DIR, ARTIFACTS_DIR
from chargeback_risk_engine.review_budget import optimize_review_budget


st.set_page_config(
    page_title="Chargeback Risk Engine",
    page_icon="🛡️",
    layout="wide",
)

st.title("Chargeback Risk Engine")
st.caption("Track 02 — AI Risk Manager")
st.write(
    "AI-assisted chargeback decisions with deterministic financial safety controls"
)


@st.cache_data
def proof_metrics():
    """Compute lightweight proof metrics directly from the public evaluation data."""
    test_path = DATA_DIR / "test.csv"

    if not test_path.exists():
        return {
            "available": False,
            "reason": f"Missing evaluation dataset: {test_path}",
        }

    test = pd.read_csv(test_path)

    with tempfile.TemporaryDirectory(prefix="cre_ui_eval_") as tmp:
        results = run_pipeline(
            test,
            db_path=str(Path(tmp) / "audit.db"),
        )

    cm = confusion_matrix_for_auto_contest(results)
    prf = precision_recall_f1(cm)
    rb = optimize_review_budget(results)

    return {
        "available": True,
        "expected_net_value": float(
            results.loc[
                results["action"] == "AUTO-CONTEST",
                "expected_net_value",
            ].sum()
        ),
        "precision": float(prf["precision"]),
        "recall": float(prf["recall"]),
        "fp_cost": float(false_positive_cost(results)),
        "review_budget": rb,
    }


score_tab, proof_tab, demo_tab = st.tabs(
    ["Decision", "Proof", "Demo cases"]
)


with score_tab:
    left, right = st.columns([1, 1.3])

    with left:
        reason_code = st.selectbox("Reason code", REASON_CODES)

        amount = st.number_input(
            "Disputed amount (₹)",
            min_value=1.0,
            value=2400.0,
            step=100.0,
        )

        dispute_id = st.text_input(
            "Case ID",
            value=f"CASE_{uuid.uuid4().hex[:8].upper()}",
        )

        st.markdown("### Evidence")

        evidence_values = {}

        for field in RELEVANT_EVIDENCE_BY_REASON[reason_code]:
            choice = st.radio(
                field.replace("_", " "),
                ["Yes", "No", "Unknown"],
                index=2,
                key=f"evidence_{field}",
                horizontal=True,
            )

            evidence_values[field] = {
                "Yes": True,
                "No": False,
                "Unknown": None,
            }[choice]

        evidence_text = st.text_area(
            "Optional case notes",
            height=90,
            help="Case notes are treated as untrusted data; they cannot change policy.",
        )

        if st.button("Run live case", type="primary"):
            dispute = {
                "dispute_id": dispute_id,
                "payment_id": "pay_streamlit_demo",
                "reason_code": reason_code,
                "amount": amount,
                "evidence_text": evidence_text,
                **evidence_values,
            }

            st.session_state.last_result = score_dispute_locally(dispute)

    with right:
        result = st.session_state.get("last_result")

        if not result:
            st.info("Enter a case and run the decision path.")
        else:
            a, b, c, d = st.columns(4)

            a.metric(
                "Win probability",
                f"{result['win_probability']:.1%}",
            )

            b.metric(
                "Evidence",
                f"{result['evidence_score']['completeness']:.0%}",
            )

            c.metric(
                "Expected net value",
                f"₹{result['economic_decision']['expected_net_value']:,.0f}",
            )

            d.metric(
                "Decision",
                result["action"],
            )

            st.markdown("### Decision waterfall")

            st.write(
                {
                    "1 · model": (
                        f"{result['win_probability']:.1%} win probability"
                    ),
                    "2 · evidence": (
                        f"{result['evidence_score']['completeness']:.0%} complete / "
                        f"{result['evidence_score']['validity']:.0%} valid"
                    ),
                    "3 · graph": result["graph_analysis"]["risk_type"],
                    "4 · economics": (
                        f"₹{result['economic_decision']['expected_net_value']:,.0f} "
                        "expected net"
                    ),
                    "5 · policy": result["action"],
                }
            )

            st.markdown("### Why?")

            st.write(result["explanation"]["policy_reason"])
            st.write(result["explanation"]["economic_reason"])
            st.write(result["explanation"]["graph_reason"])

            st.markdown("### Evidence analyst")
            st.json(result["explanation"]["ai_analyst"])

            if result.get("counterfactual"):
                st.markdown("### What would change this?")
                st.write(result["counterfactual"]["statement"])

            with st.expander("Graph"):
                st.json(result["graph_analysis"])

            with st.expander("Audit"):
                st.write(
                    {
                        "audit_id": result["audit_id"],
                        "request_id": result["request_id"],
                        "model": result["model_version"],
                        "policy": result["policy_version"],
                    }
                )

            if result.get("contest_draft"):
                with st.expander("Contest draft"):
                    st.caption(
                        "Draft only. No external financial action is executed."
                    )
                    st.json(result["contest_draft"])


with proof_tab:
    st.subheader("Measured system proof")
    st.caption(
        "Bundled synthetic evaluation data; not a production-performance claim."
    )

    report_path = ARTIFACTS_DIR / "verification_report.json"

    if report_path.exists():
        try:
            raw = json.loads(report_path.read_text(encoding="utf-8"))

            h = raw.get("headline", {})

            review_budget_rows = raw.get("review_budget", [])
            rb10 = next(
                (
                    row
                    for row in review_budget_rows
                    if float(row.get("review_budget", 0)) == 0.10
                ),
                None,
            )

            a, b, c, d, e, f = st.columns(6)

            a.metric(
                "PR-AUC",
                f"{h.get('pr_auc', 0):.3f}",
            )

            b.metric(
                "Precision",
                f"{h.get('auto_contest_precision', 0):.1%}",
            )

            c.metric(
                "Recall",
                f"{h.get('auto_contest_recall', 0):.1%}",
            )

            d.metric(
                "Realized net value",
                f"₹{h.get('realized_net_value', 0):,.0f}",
            )

            e.metric(
                "10% review capacity",
                (
                    f"+{rb10.get('recall_at_budget', 0):.1%} recall"
                    if rb10
                    else "N/A"
                ),
            )

            f.metric(
                "Hard cases",
                f"{h.get('hard_cases_passed', 0)}/{h.get('hard_cases_total', 0)}",
            )

            st.markdown("### Strategy comparison")

            baselines = raw.get("baselines", [])

            if baselines:
                st.dataframe(
                    pd.DataFrame(baselines)[
                        [
                            "strategy",
                            "auto_contest_count",
                            "auto_contest_precision",
                            "auto_contest_recall",
                            "realized_net_value",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

            st.markdown("### True ablation")
            st.caption(
                "Each row removes a specific capability; the report does not relabel "
                "one pipeline as several."
            )

            ablation = raw.get("ablation", [])

            if ablation:
                st.dataframe(
                    pd.DataFrame(ablation)[
                        [
                            "component",
                            "auto_contest_count",
                            "precision",
                            "recall",
                            "realized_net_value",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

            st.markdown("### Review-budget optimization")

            if review_budget_rows:
                st.dataframe(
                    pd.DataFrame(review_budget_rows),
                    use_container_width=True,
                    hide_index=True,
                )

            per_reason = raw.get("per_reason", [])

            if per_reason:
                with st.expander("Per-reason evaluation"):
                    st.dataframe(
                        pd.DataFrame(per_reason),
                        use_container_width=True,
                        hide_index=True,
                    )

            with st.expander("Security and reproducibility"):
                st.json(
                    {
                        "security": raw.get("security", {}),
                        "reproducibility": raw.get("reproducibility", {}),
                        "confidence_intervals": raw.get(
                            "confidence_intervals",
                            {},
                        ),
                    }
                )

        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            st.error("Unable to load verification report.")
            st.caption(f"Report parsing error: {exc}")

    else:
        metrics = proof_metrics()

        if metrics.get("available"):
            a, b, c, d, e = st.columns(5)

            a.metric(
                "Precision",
                f"{metrics['precision']:.1%}",
            )

            b.metric(
                "Recall",
                f"{metrics['recall']:.1%}",
            )

            c.metric(
                "Expected net value",
                f"₹{metrics['expected_net_value']:,.0f}",
            )

            d.metric(
                "False-positive cost",
                f"₹{metrics['fp_cost']:,.0f}",
            )

            e.metric(
                "Review budget",
                str(metrics["review_budget"]),
            )

            st.info(
                "Detailed verification artifacts are not bundled; "
                "the proof metrics above are computed directly from the "
                "public evaluation dataset."
            )
        else:
            st.warning(
                metrics.get(
                    "reason",
                    "Verification artifacts are unavailable.",
                )
            )


with demo_tab:
    st.subheader("Deterministic demo cases")

    demo_cases = [
        (
            "CASE 1 — strong evidence",
            {
                "dispute_id": "DEMO_AUTO_UI",
                "payment_id": "pay_demo_1",
                "reason_code": "item_not_received",
                "amount": 2400.0,
                "customer_id": "ui_unique",
                "device_id": "ui_unique_device",
                "ip_address": "10.9.0.1",
                "merchant_id": "merchant_demo",
                "has_tracking_number": True,
                "has_delivery_confirmation": True,
                "has_signature_confirmation": True,
            },
        ),
        (
            "CASE 2 — mixed evidence",
            {
                "dispute_id": "DEMO_REVIEW_UI",
                "payment_id": "pay_demo_2",
                "reason_code": "item_not_received",
                "amount": 2400.0,
                "customer_id": "ui_review",
                "device_id": "ui_review_device",
                "has_tracking_number": True,
                "has_delivery_confirmation": None,
                "has_signature_confirmation": None,
            },
        ),
        (
            "CASE 3 — network escalation",
            {
                "dispute_id": "DEMO_RING_UI",
                "payment_id": "pay_demo_3",
                "reason_code": "item_not_received",
                "amount": 2400.0,
                "customer_id": "ui_ring_customer",
                "device_id": "shared-device",
                "ip_address": "10.0.0.9",
                "merchant_id": "merchant_demo",
                "has_tracking_number": True,
                "has_delivery_confirmation": True,
                "has_signature_confirmation": True,
            },
        ),
        (
            "CASE 4 — weak evidence",
            {
                "dispute_id": "DEMO_WEAK_UI",
                "payment_id": "pay_demo_4",
                "reason_code": "item_not_as_described",
                "amount": 1800.0,
                "customer_id": "ui_weak",
                "device_id": "ui_weak_device",
                "has_product_photos": None,
                "has_item_description_match": False,
                "has_return_communication": None,
            },
        ),
        (
            "CASE 5 — economic boundary",
            {
                "dispute_id": "DEMO_ECON_UI",
                "payment_id": "pay_demo_5",
                "reason_code": "duplicate_charge",
                "amount": 500.0,
                "customer_id": "ui_econ",
                "device_id": "ui_econ_device",
                "has_duplicate_transaction_proof": True,
                "has_refund_already_issued": False,
            },
        ),
    ]

    for title, case in demo_cases:
        with st.expander(
            title,
            expanded=(title == "CASE 1 — strong evidence"),
        ):
            if st.button(
                f"Run {title}",
                key=case["dispute_id"],
            ):
                if title.startswith("CASE 3"):
                    seed = [
                        {
                            "dispute_id": "RING_SEED_A",
                            "reason_code": "item_not_received",
                            "amount": 2200.0,
                            "customer_id": "ring_a",
                            "device_id": "shared-device",
                            "ip_address": "10.0.0.9",
                            "merchant_id": "merchant_demo",
                            "has_tracking_number": True,
                            "has_delivery_confirmation": True,
                            "has_signature_confirmation": True,
                        },
                        {
                            "dispute_id": "RING_SEED_B",
                            "reason_code": "item_not_received",
                            "amount": 1800.0,
                            "customer_id": "ring_b",
                            "device_id": "shared-device",
                            "ip_address": "10.0.0.9",
                            "merchant_id": "merchant_demo",
                            "has_tracking_number": True,
                            "has_delivery_confirmation": True,
                            "has_signature_confirmation": True,
                        },
                    ]

                    graph = RiskGraph(seed)

                    st.session_state.demo_result = decide_case(
                        case,
                        risk_graph=graph,
                        include_counterfactual=False,
                    )
                else:
                    st.session_state.demo_result = score_dispute_locally(case)

                st.session_state.demo_case = case["dispute_id"]

            result = (
                st.session_state.get("demo_result")
                if st.session_state.get("demo_case")
                == case["dispute_id"]
                else None
            )

            if result:
                st.json(result)
            else:
                st.caption("Deterministic demo input")

