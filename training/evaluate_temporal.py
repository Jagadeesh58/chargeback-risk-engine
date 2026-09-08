"""Chronological ordering check for the synthetic dataset.

The generated dates are synthetic and are not evidence of production time
shift. This script checks whether a chronological train/test split remains
runnable without presenting it as temporal robustness proof.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from chargeback_risk_engine.ml_scorer import MLScorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR


def main():
    frames = [pd.read_csv(DATA_DIR / f"{name}.csv") for name in ("train", "dev", "test")]
    df = pd.concat(frames, ignore_index=True)
    df["respond_by"] = pd.to_datetime(df["respond_by"])
    df = df.sort_values("respond_by").reset_index(drop=True)
    cut = int(len(df) * 0.80)
    train, test = df.iloc[:cut], df.iloc[cut:]

    model = MLScorer().fit(train)
    probs = []
    for _, row in test.iterrows():
        dispute = row.to_dict()
        for key, value in dispute.items():
            if isinstance(value, float) and pd.isna(value):
                dispute[key] = None
        probs.append(model.predict_win_probability(dispute))
    y = test["would_win"].astype(int)

    results = {
        "type": "chronological_ordering_check",
        "scientific_scope": "Synthetic dates are not evidence of production temporal robustness.",
        "train_rows": len(train),
        "test_rows": len(test),
        "train_end": train["respond_by"].max().date().isoformat(),
        "test_start": test["respond_by"].min().date().isoformat(),
        "live_model": "logreg-v1",
        "metrics": {
            "roc_auc": float(roc_auc_score(y, probs)),
            "pr_auc": float(average_precision_score(y, probs)),
            "brier_score": float(brier_score_loss(y, probs)),
        },
    }
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    (ARTIFACTS_DIR / "temporal_evaluation.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
