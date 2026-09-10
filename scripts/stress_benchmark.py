"""Held-out stress benchmark: missingness, contradiction, and amount-shift robustness."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.policy import AUTO_CONTEST, decide
from chargeback_risk_engine.policy_profile import decision_score, load_policy_profile
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.config import ALL_EVIDENCE_FIELDS
from chargeback_risk_engine.monitoring.drift_guard import detect_drift, to_dict


def _eval(df: pd.DataFrame, scorer, profile) -> dict:
    actions = []
    probs = []
    for row in df.to_dict("records"):
        for k, v in list(row.items()):
            if isinstance(v, float) and pd.isna(v):
                row[k] = None
        p = scorer.predict_win_probability(row)
        q = score_evidence(row, assemble(row))
        s = decision_score(p, q.confidence, evidence_signal_weight=profile.evidence_signal_weight)
        d = decide(
            p, float(row["amount"]), evidence_packet=assemble(row), evidence_quality=q,
            expected_net_value=p * float(row["amount"]) - 150.0,
            decision_score=s, auto_contest_threshold=profile.auto_contest_threshold,
            accept_loss_threshold=profile.accept_loss_threshold,
            monetary_ceiling=profile.monetary_ceiling,
            min_evidence_completeness=profile.min_evidence_completeness,
        )
        actions.append(d.action); probs.append(p)
    auto = np.asarray(actions) == AUTO_CONTEST
    y = df["would_win"].astype(bool).to_numpy()
    n = int(auto.sum()); tp = int((auto & y).sum())
    return {
        "rows": len(df), "auto_contest": n,
        "precision": tp / n if n else 0.0,
        "recall": tp / int(y.sum()) if y.sum() else 0.0,
        "auto_rate": n / len(df) if len(df) else 0.0,
    }


def main() -> None:
    test = pd.read_csv(DATA_DIR / "test.csv")
    stress = test.sample(n=min(1000, len(test)), random_state=42).reset_index(drop=True)
    scorer = load_or_fit_ml_scorer(); profile = load_policy_profile()
    rng = np.random.default_rng(42)

    missing = stress.copy()
    for col in ALL_EVIDENCE_FIELDS:
        mask = rng.random(len(missing)) < 0.25
        missing.loc[mask, col] = np.nan

    contradiction = stress.copy()
    contradiction_mask = rng.random(len(contradiction)) < 0.20
    for col in ALL_EVIDENCE_FIELDS:
        contradiction.loc[contradiction_mask, col] = False
    if "has_tracking_number" in contradiction:
        contradiction.loc[contradiction_mask, "has_tracking_number"] = True
    if "has_delivery_confirmation" in contradiction:
        contradiction.loc[contradiction_mask, "has_delivery_confirmation"] = False

    amount_shift = stress.copy()
    amount_shift["amount"] = amount_shift["amount"] * rng.lognormal(mean=0.35, sigma=0.25, size=len(amount_shift))

    baseline = {"amount": test["amount"].tolist()[:2000]}
    current = {"amount": amount_shift["amount"].tolist()[:2000]}
    drift = detect_drift(baseline, current)

    result = {
        "protocol": "stress_transformations_of_frozen_test_only",
        "sample_rows_per_stress_case": len(stress),
        "not_external_data": True,
        "baseline": _eval(stress, scorer, profile),
        "missingness_25pct": _eval(missing, scorer, profile),
        "contradiction_20pct": _eval(contradiction, scorer, profile),
        "amount_shift": _eval(amount_shift, scorer, profile),
        "drift_report": to_dict(drift),
        "honesty": "These are robustness stress tests, not independent external-data claims.",
    }
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    (ARTIFACTS_DIR / "stress_benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
