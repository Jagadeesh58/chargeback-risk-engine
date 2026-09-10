"""Development-split policy tuning with frozen, auditable constraints.

The optimizer never reads the final test set. It searches a small, transparent
threshold grid on ``dev.csv`` and writes the frozen policy profile consumed by
benchmark/report tooling. The production decision function remains
fully deterministic and the model never receives authority over the action.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.paths import ARTIFACTS_DIR, DATA_DIR
from chargeback_risk_engine.policy import (
    ACCEPT_LOSS_THRESHOLD,
    AUTO_CONTEST_THRESHOLD,
    CONTEST_COST,
    MIN_EVIDENCE_COMPLETENESS,
)

POLICY_PROFILE_PATH = ARTIFACTS_DIR / "policy_profile.json"


@dataclass(frozen=True)
class PolicyProfile:
    policy_version: str
    auto_contest_threshold: float
    accept_loss_threshold: float
    monetary_ceiling: float
    min_evidence_completeness: float
    contest_cost: float
    selection_split: str
    objective: str
    constraints: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _model_probabilities(df: pd.DataFrame) -> np.ndarray:
    scorer = load_or_fit_ml_scorer()
    probs = []
    for row in df.to_dict("records"):
        probs.append(scorer.predict_win_probability(row))
    return np.asarray(probs, dtype=float)


def evaluate_threshold(df: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> dict:
    rows = []
    for row, p in zip(df.to_dict("records"), probabilities):
        packet = assemble(row)
        quality = score_evidence(row, packet)
        eligible = quality.completeness >= MIN_EVIDENCE_COMPLETENESS and quality.validity >= 1.0
        auto = bool(p >= threshold and eligible and float(row["amount"]) <= 50_000)
        truth = bool(row["would_win"])
        ev = calculate_economic_value(float(row["amount"]), float(p))
        rows.append((auto, truth, float(row["amount"]), ev.expected_recovery))

    auto_rows = [x for x in rows if x[0]]
    tp = sum(x[1] for x in auto_rows)
    fp = len(auto_rows) - tp
    total_positive = int(df["would_win"].sum())
    precision = tp / len(auto_rows) if auto_rows else 0.0
    recall = tp / total_positive if total_positive else 0.0
    expected_recovery = sum(x[3] for x in auto_rows)
    net_value = expected_recovery - len(auto_rows) * CONTEST_COST
    return {
        "threshold": float(threshold),
        "auto_contest_count": len(auto_rows),
        "auto_contest_rate": len(auto_rows) / len(df),
        "precision": precision,
        "recall": recall,
        "expected_recovery": expected_recovery,
        "expected_net_value": net_value,
        "false_positive_count": fp,
        "review_rate": 1.0 - len(auto_rows) / len(df),
    }


def optimize_policy(
    dev: pd.DataFrame | None = None,
    *,
    thresholds: list[float] | None = None,
    min_precision: float = 0.72,
    max_auto_rate: float = 0.40,
) -> tuple[PolicyProfile, list[dict]]:
    dev = dev if dev is not None else pd.read_csv(DATA_DIR / "dev.csv")
    thresholds = thresholds or [round(x, 3) for x in np.arange(0.55, 0.831, 0.005)]
    probabilities = _model_probabilities(dev)
    candidates = [evaluate_threshold(dev, probabilities, t) for t in thresholds]
    feasible = [
        c for c in candidates
        if c["precision"] >= min_precision and c["auto_contest_rate"] <= max_auto_rate
    ]
    if not feasible:
        feasible = candidates
    best = max(feasible, key=lambda c: (c["expected_net_value"], c["precision"], -c["auto_contest_rate"]))
    profile = PolicyProfile(
        policy_version="policy-v5-dev-optimized",
        auto_contest_threshold=best["threshold"],
        accept_loss_threshold=ACCEPT_LOSS_THRESHOLD,
        monetary_ceiling=50_000.0,
        min_evidence_completeness=MIN_EVIDENCE_COMPLETENESS,
        contest_cost=CONTEST_COST,
        selection_split="dev.csv only",
        objective="maximize expected net value subject to precision >= 0.72 and auto-contest rate <= 0.40",
        constraints={"min_precision": min_precision, "max_auto_rate": max_auto_rate},
    )
    return profile, candidates


def save_policy_profile(profile: PolicyProfile, path: str | Path = POLICY_PROFILE_PATH) -> None:
    Path(path).parent.mkdir(exist_ok=True)
    Path(path).write_text(json.dumps(profile.to_dict(), indent=2))


if __name__ == "__main__":
    p, candidates = optimize_policy()
    save_policy_profile(p)
    print(json.dumps({"selected": p.to_dict(), "top_candidates": sorted(candidates, key=lambda x: x["expected_net_value"], reverse=True)[:10]}, indent=2))
