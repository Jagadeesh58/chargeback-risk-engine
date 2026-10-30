# Model Card

## Intended use

Rank the likely success of a merchant chargeback dispute so downstream policy can decide whether to contest automatically, route to a human, or accept the loss.

## Model

The live model is a reason-code-specific Logistic Regression model trained only on relevant evidence fields. Unknown fields are explicitly encoded as uncertainty (0.5) rather than silently treated as positive evidence.

Rules and the HistGradientBoosting challenger (PR-AUC 0.7254) are retained for offline comparison.

## Evaluation protocol

- train: `data/train.csv` (20,000 rows)
- model-selection / calibration: `data/dev.csv` (5,000 rows)
- final evaluation: `data/test.csv` (5,000 rows)
- no `would_win` value is supplied to the live scorer
- policy tuning is performed on development data only

## Current result

The bundled test snapshot reports:
- PR-AUC: **0.7234** (vs. rules baseline 0.7087, HGB challenger 0.7254, and theoretical oracle ceiling 0.7917)
- ROC-AUC: **0.6971** (vs. rules baseline 0.6951 and theoretical oracle ceiling 0.8156)
- Normalized Chance-Adjusted Skill: **62.5%** of oracle Gini skill; **69.9%** of oracle normalized PR skill
- Policy operating point (0.65 threshold): 74.8% precision and 43.9% recall
- Automated realized net value: **₹49.73L** (conservative automation with 66.5% held for manual review valued at ₹0)

## Known limitations

1. **Synthetic data**: The data is synthetic and evidence-only. It does not prove production fraud generalization.
2. **Amount invariance**: The ML scorer operates strictly on reason codes and evidence validity flags; it does not take dispute amount as a feature. Dispute amount and monetary ceilings are enforced downstream by the deterministic economic and policy layers.
3. **Modest ML lift over rules**: Machine learning achieves only modest lift over rules (0.723 vs 0.709 PR-AUC) because synthetic ground truth is generated from noisy evidence rules.
4. **Graph separation**: The graph layer is tested separately because the tabular dataset does not contain historical network identifiers.
