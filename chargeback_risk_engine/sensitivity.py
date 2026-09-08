"""Sensitivity analysis using the canonical policy authority."""
from __future__ import annotations

import pandas as pd

from chargeback_risk_engine.engine.economic_decision import calculate_economic_value
from chargeback_risk_engine.engine.evidence_score import score_evidence
from chargeback_risk_engine.evidence import assemble
from chargeback_risk_engine.metrics import _row_to_dispute
from chargeback_risk_engine.ml_scorer import load_or_fit_ml_scorer
from chargeback_risk_engine.policy import (
    ACCEPT_LOSS_THRESHOLD,
    AUTO_CONTEST_THRESHOLD,
    MONETARY_CEILING,
    decide,
)


def _precompute(df: pd.DataFrame) -> list[dict]:
    ml = load_or_fit_ml_scorer()
    rows = []
    for _, row in df.iterrows():
        dispute = _row_to_dispute(row)
        packet = assemble(dispute)
        quality = score_evidence(dispute, packet)
        probability = ml.predict_win_probability(dispute)
        economic = calculate_economic_value(dispute["amount"], probability)
        rows.append({
            "amount": dispute["amount"],
            "would_win": dispute["would_win"],
            "probability": probability,
            "packet": packet,
            "quality": quality,
            "economic": economic,
        })
    return rows


def sweep_auto_contest_threshold(
    df: pd.DataFrame,
    thresholds: list[float],
    contest_cost: float = 150.0,
) -> pd.DataFrame:
    precomputed = _precompute(df)
    results = []
    for threshold in thresholds:
        tp = fp = fn = 0
        for row in precomputed:
            decision = decide(
                row["probability"],
                row["amount"],
                evidence_packet=row["packet"],
                evidence_quality=row["quality"],
                expected_net_value=row["economic"].expected_net_value,
                auto_contest_threshold=threshold,
            )
            predicted_win = decision.action == "AUTO-CONTEST"
            actual_win = row["would_win"] is True
            if predicted_win and actual_win:
                tp += 1
            elif predicted_win and not actual_win:
                fp += 1
            elif not predicted_win and actual_win:
                fn += 1
        results.append({
            "threshold": threshold,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "auto_contest_count": tp + fp,
            "false_positive_cost": fp * contest_cost,
        })
    return pd.DataFrame(results)


def sweep_monetary_ceiling(
    df: pd.DataFrame,
    ceilings: list[float],
    contest_cost: float = 150.0,
) -> pd.DataFrame:
    precomputed = _precompute(df)
    results = []
    for ceiling in ceilings:
        tp = fp = human_review_count = 0
        for row in precomputed:
            decision = decide(
                row["probability"],
                row["amount"],
                evidence_packet=row["packet"],
                evidence_quality=row["quality"],
                expected_net_value=row["economic"].expected_net_value,
                auto_contest_threshold=AUTO_CONTEST_THRESHOLD,
                accept_loss_threshold=ACCEPT_LOSS_THRESHOLD,
                monetary_ceiling=ceiling,
            )
            if decision.action == "HUMAN-REVIEW":
                human_review_count += 1
            elif decision.action == "AUTO-CONTEST":
                if row["would_win"] is True:
                    tp += 1
                else:
                    fp += 1
        results.append({
            "ceiling": ceiling,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "auto_contest_count": tp + fp,
            "human_review_count": human_review_count,
            "false_positive_cost": fp * contest_cost,
        })
    return pd.DataFrame(results)
