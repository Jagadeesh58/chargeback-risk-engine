# Judge Guide — Chargeback Risk Engine

## 90-second demo

### 0–15s — The decision

Open the **Decision** tab and run a fully-supported `item_not_received` case.

Show:

- win probability
- evidence completeness
- expected net value
- final action

Say: **“The model never decides the money movement by itself.”**

### 15–30s — Why this case is safe

Point to the evidence, graph, economics and policy explanation.

Say: **“A high score is not enough: evidence, economics and safety policy all have to pass.”**

### 30–45s — A failure case

Run the missing-evidence scenario.

Say: **“When information is incomplete, the system abstains rather than hallucinating certainty.”**

### 45–60s — Adversarial case

Run or show the graph-ring / prompt-injection hard case.

Say: **“The notes are untrusted text; they cannot rewrite policy. Relationship risk can force human review.”**

### 60–75s — What would change the decision

Use the counterfactual panel.

Say: **“The system can tell an analyst the smallest evidence change that would move the case across a decision boundary.”**

### 75–90s — Proof

Open the **Proof** tab.

Show:

- held-out PR-AUC
- precision/recall
- true ablation
- analyst review budgets
- hard-case pass count

Finish with: **“Every automated decision has a reproducible policy path and durable audit record.”**

## Judge questions to pre-answer

### Why not let the LLM choose the action?

Because a model that can directly choose a financial action is a larger safety and reproducibility surface. The LLM is intentionally bounded to evidence analysis and drafting.

### Why synthetic data?

The repository does not claim access to production Razorpay chargeback labels. Synthetic data is used to make the evaluation reproducible, and limitations are explicitly disclosed.

### Why is recall only around 40%?

The operating point deliberately favors precision and safety. Cases that are high-value but ambiguous are routed to human review rather than forced into an automatic action.

### Why is the graph lift not shown on the main test set?

Because the public tabular dataset does not contain historical relationship identifiers. Claiming a graph lift there would be misleading. The graph is measured through explicit network hard cases instead.

## Evidence map

| Claim | Evidence |
|---|---|
| deterministic policy | `chargeback_risk_engine/policy.py` |
| risk model | `chargeback_risk_engine/ml_scorer.py` |
| economics | `chargeback_risk_engine/engine/economic_decision.py` |
| graph | `chargeback_risk_engine/engine/risk_graph.py` |
| AI boundary | `chargeback_risk_engine/ai_analyst.py` |
| idempotency/audit | `chargeback_risk_engine/audit_log.py` |
| hard cases | `scripts/evaluate_hard_cases.py` |
| ablation | `scripts/generate_report.py` |
| held-out benchmark | `scripts/benchmark.py` |
