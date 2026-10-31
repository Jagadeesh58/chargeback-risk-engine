"""Unit tests for the shared symmetric dispute cost model.

Verifies the mathematical and accounting invariants of evaluate_strategy_outcome:
1. Penalty applies only to lost contests (wins pay 0 penalty; uncontested losses pay 0 penalty).
2. Identical contested sets produce identical penalty totals regardless of strategy details.
3. At p = 0, strategy net values match committed values in strategy_comparison.json to the paisa (0.01 INR).
4. Slope invariant: net_value(p1) - net_value(p2) == -(p1 - p2) * lost_contest_count.
5. Contest and review fees are charged exactly once per case.
6. Guard test asserting all strategies use the shared function without bypassing it.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from chargeback_risk_engine.paths import ARTIFACTS_DIR
from scripts.generate_report import (
    CONTEST_COST,
    HUMAN_REVIEW_COST,
    evaluate_strategy_outcome,
    compute_strategy_comparison,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_case(dispute_id: str, amount: float, would_win: bool, p_win: float = 0.5) -> dict:
    return {
        "dispute_id": dispute_id,
        "amount": float(amount),
        "would_win": bool(would_win),
        "p_win": float(p_win),
        "action": "AUTO-CONTEST",
    }


def test_penalty_applies_only_to_lost_contests():
    """Penalty applies exclusively to contested losses.
    
    - Contested win: loss_penalty = 0.
    - Uncontested loss: loss_penalty = 0.
    - Contested loss: loss_penalty = p.
    """
    cases = [
        _make_case("c1", amount=1000.0, would_win=True),   # Contested win
        _make_case("c2", amount=2000.0, would_win=False),  # Uncontested loss
        _make_case("c3", amount=3000.0, would_win=False),  # Contested loss
    ]
    auto_mask = np.array([True, False, True], dtype=bool)
    review_mask = np.zeros(3, dtype=bool)
    penalty_p = 4150.0

    ev = evaluate_strategy_outcome(
        cases,
        auto_mask,
        review_mask,
        review_treatment="none",
        contest_cost=CONTEST_COST,
        review_cost=HUMAN_REVIEW_COST,
        loss_penalty=penalty_p,
    )

    assert ev["contested_count"] == 2
    assert ev["lost_contest_count"] == 1
    assert ev["loss_penalty"] == penalty_p

    # Individual case net values:
    # Case 1 (win): 1000 - 150 = 850
    # Case 2 (uncontested): 0
    # Case 3 (loss): -150 - 4150 = -4300
    per_case = ev["per_case_net"]
    assert pytest.approx(per_case[0]) == 1000.0 - CONTEST_COST
    assert pytest.approx(per_case[1]) == 0.0
    assert pytest.approx(per_case[2]) == -CONTEST_COST - penalty_p
    assert pytest.approx(ev["realized_net_value"]) == 850.0 + 0.0 - 4300.0


def test_identical_contested_sets_produce_identical_penalty_totals():
    """Any two strategies that contest the same subset pay the exact same penalty total."""
    cases = [
        _make_case("c1", amount=1200.0, would_win=True),
        _make_case("c2", amount=2500.0, would_win=False),
        _make_case("c3", amount=1800.0, would_win=False),
        _make_case("c4", amount=4000.0, would_win=True),
    ]
    # Strategy A contests c1 and c2 via automated contest
    auto_mask_a = np.array([True, True, False, False], dtype=bool)
    review_mask_a = np.zeros(4, dtype=bool)

    # Strategy B contests c1 and c2 via human review
    auto_mask_b = np.zeros(4, dtype=bool)
    review_mask_b = np.array([True, True, False, False], dtype=bool)

    penalty_p = 5000.0

    ev_a = evaluate_strategy_outcome(
        cases, auto_mask_a, review_mask_a, "none",
        CONTEST_COST, HUMAN_REVIEW_COST, loss_penalty=penalty_p,
    )
    ev_b = evaluate_strategy_outcome(
        cases, auto_mask_b, review_mask_b, "observed_ground_truth",
        CONTEST_COST, HUMAN_REVIEW_COST, loss_penalty=penalty_p,
    )

    assert ev_a["contested_count"] == ev_b["contested_count"] == 2
    assert ev_a["lost_contest_count"] == ev_b["lost_contest_count"] == 1
    assert ev_a["loss_penalty"] == ev_b["loss_penalty"] == penalty_p


def test_zero_penalty_matches_committed_values_to_paisa():
    """At p = 0, every strategy's net value matches committed strategy_comparison.json to 0.01 INR."""
    strat_file = ARTIFACTS_DIR / "strategy_comparison.json"
    bm_file = ARTIFACTS_DIR / "candidate_benchmark.json"
    oracle_file = ARTIFACTS_DIR / "oracle_ceiling.json"

    assert strat_file.exists(), "strategy_comparison.json missing"
    assert bm_file.exists(), "candidate_benchmark.json missing"

    strat_data = json.loads(strat_file.read_text(encoding="utf-8"))
    bm_data = json.loads(bm_file.read_text(encoding="utf-8"))
    oracle_data = json.loads(oracle_file.read_text(encoding="utf-8")) if oracle_file.exists() else {}

    recomputed = compute_strategy_comparison(bm_data["case_results"], oracle_data)

    for row_c, row_r in zip(strat_data["strategy_table"], recomputed["strategy_table"]):
        assert row_c["strategy"] == row_r["strategy"]
        assert pytest.approx(row_c["realized_net_value_p0"], abs=0.01) == row_r["realized_net_value_p0"]
        assert pytest.approx(row_c["realized_net_value_base_p"], abs=0.01) == row_r["realized_net_value_base_p"]


def test_slope_invariant_across_penalties():
    """The derivative of net value with respect to loss penalty p equals -lost_contest_count."""
    cases = [
        _make_case("c1", amount=1500.0, would_win=False),
        _make_case("c2", amount=3000.0, would_win=False),
        _make_case("c3", amount=4500.0, would_win=True),
    ]
    auto_mask = np.ones(3, dtype=bool)
    no_mask = np.zeros(3, dtype=bool)

    p1 = 1000.0
    p2 = 7500.0

    ev_1 = evaluate_strategy_outcome(cases, auto_mask, no_mask, "none", CONTEST_COST, HUMAN_REVIEW_COST, loss_penalty=p1)
    ev_2 = evaluate_strategy_outcome(cases, auto_mask, no_mask, "none", CONTEST_COST, HUMAN_REVIEW_COST, loss_penalty=p2)

    losses = ev_1["lost_contest_count"]  # 2 losses
    delta_p = p2 - p1
    delta_net = ev_2["realized_net_value"] - ev_1["realized_net_value"]

    assert losses == 2
    assert pytest.approx(delta_net) == -delta_p * losses


def test_contest_and_review_fees_charged_once_per_case():
    """Review and contest fees are charged exactly once per case."""
    cases = [
        _make_case("c1", amount=2000.0, would_win=True),
        _make_case("c2", amount=2000.0, would_win=False),
        _make_case("c3", amount=2000.0, would_win=True),
        _make_case("c4", amount=2000.0, would_win=False),
    ]
    # 2 automated, 1 review, 1 accepted
    auto_mask = np.array([True, True, False, False], dtype=bool)
    review_mask = np.array([False, False, True, False], dtype=bool)

    # Treatment none: reviewed case is not contested
    ev_none = evaluate_strategy_outcome(cases, auto_mask, review_mask, "none", CONTEST_COST, HUMAN_REVIEW_COST, loss_penalty=0.0)
    assert ev_none["contested_count"] == 2
    assert ev_none["contest_cost"] == 2 * CONTEST_COST
    assert ev_none["review_cost"] == 0.0

    # Treatment observed_ground_truth: reviewed case is contested
    ev_rev = evaluate_strategy_outcome(cases, auto_mask, review_mask, "observed_ground_truth", CONTEST_COST, HUMAN_REVIEW_COST, loss_penalty=0.0)
    assert ev_rev["contested_count"] == 3
    assert ev_rev["contest_cost"] == 3 * CONTEST_COST
    assert ev_rev["review_cost"] == 1 * HUMAN_REVIEW_COST


def test_guard_no_strategy_bypasses_shared_cost_model():
    """Guard test asserting every strategy in the evaluation uses the shared cost function."""
    import inspect
    import scripts.generate_report as gr

    # Inspect compute_strategy_comparison source to ensure evaluate_strategy_outcome is called
    source = inspect.getsource(gr.compute_strategy_comparison)
    assert "evaluate_strategy_outcome(" in source
    assert "evaluations[name] = {" in source

    # Assert that all strategies in strategy_comparison.json match evaluate_strategy_outcome
    strat_file = ARTIFACTS_DIR / "strategy_comparison.json"
    strat_data = json.loads(strat_file.read_text(encoding="utf-8"))

    for row in strat_data["strategy_table"]:
        # Verify that net_base_p equals net_p0 - lost_contest_count * ASSUMED_LOSS_PENALTY_INR
        net_0 = row["realized_net_value_p0"]
        net_base = row["realized_net_value_base_p"]
        losses = row["lost_contest_count"]
        expected_base = net_0 - losses * strat_data["assumed_loss_penalty_inr"]
        assert pytest.approx(net_base, abs=0.01) == expected_base, (
            f"Strategy {row['strategy']} bypasses linear loss penalty formula: "
            f"expected {expected_base}, found {net_base}"
        )
