"""Optional external-dataset evaluator.

Use this with a CSV that contains ``reason_code``, ``amount``, the relevant
boolean evidence fields, and ``would_win``. This script never modifies the
bundled train/dev/test data and is intentionally kept separate from release
claims so an external dataset cannot be accidentally mixed into the headline
benchmark.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from chargeback_risk_engine.config import ALL_EVIDENCE_FIELDS
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.policy_profile import load_policy_profile, decision_score
from chargeback_risk_engine.policy import decide, AUTO_CONTEST


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", help="External held-out CSV")
    parser.add_argument("--output", default="artifacts/external_benchmark.json")
    args = parser.parse_args()
    df = pd.read_csv(args.csv)
    required = {"reason_code", "amount", "would_win", *ALL_EVIDENCE_FIELDS}
    missing = sorted(required - set(df.columns))
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")
    scorer = load_or_fit_ml_scorer()
    profile = load_policy_profile()
    actions = []
    probs = []
    for row in df.to_dict("records"):
        for k, v in list(row.items()):
            if isinstance(v, float) and pd.isna(v): row[k] = None
        p = scorer.predict_win_probability(row)
        q = score_evidence(row, assemble(row))
        s = decision_score(p, q.confidence, evidence_signal_weight=profile.evidence_signal_weight)
        d = decide(p, row["amount"], evidence_packet=assemble(row), evidence_quality=q,
                   expected_net_value=p * float(row["amount"]) - 150.0,
                   decision_score=s, auto_contest_threshold=profile.auto_contest_threshold,
                   accept_loss_threshold=profile.accept_loss_threshold,
                   monetary_ceiling=profile.monetary_ceiling,
                   min_evidence_completeness=profile.min_evidence_completeness)
        probs.append(p); actions.append(d.action)
    auto = [i for i, a in enumerate(actions) if a == AUTO_CONTEST]
    y = df["would_win"].astype(bool).tolist()
    tp = sum(y[i] for i in auto)
    precision = tp / len(auto) if auto else 0.0
    recall = tp / sum(y) if sum(y) else 0.0
    result = {"rows": len(df), "auto_contest": len(auto), "precision": precision, "recall": recall,
              "model_source": "bundled-train-artifact; external data used for evaluation only"}
    Path(args.output).parent.mkdir(exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

if __name__ == "__main__": main()
