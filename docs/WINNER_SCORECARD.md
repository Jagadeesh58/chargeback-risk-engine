# Winner Scorecard

This file is intentionally a **strategy document, not a claim of first place**. The 65-repository comparison is subjective and judging is external.

## What the submission should win on

### 1. Safety with useful abstention

The model cannot directly authorize a financial action. The deterministic policy can force human review for missing/contradictory evidence, network risk, retry limits, service failures, and monetary ceilings.

### 2. Economic decision quality

The system evaluates expected recovery and contest cost rather than optimizing a classifier metric alone. Review capacity is treated as an explicit business constraint.

### 3. Evidence-aware AI

AI is bounded to evidence analysis and contest drafting. The final action is independently determined by deterministic policy.

### 4. Reproducible proof

The submission separates train/dev/test, keeps test outcomes out of policy tuning, reports realized and expected economics separately, includes per-reason metrics, and runs a frozen hard-case suite.

### 5. Honest limitations

The dataset is synthetic. The graph layer is not claimed to improve the tabular benchmark because the public test data contains no historical network identifiers. This prevents an inflated claim from weakening the rest of the submission.

## Competition strategy

The strongest competing patterns in the reviewed submissions are:

- dramatic offline ML metrics
- highly polished live demos
- finance-control/verifier architectures
- agentic-commerce safety gates

The intended counter-position is:

> **A chargeback decision is a financial-control problem, not only a classification problem.**

The demo and proof package should therefore lead with decision quality, safety and economic value, then show the ML details.
