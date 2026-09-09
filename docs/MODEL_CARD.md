# Model Card

## Intended use

Rank the likely success of a merchant chargeback dispute so downstream policy can decide whether to contest automatically, route to a human, or accept the loss.

## Model

The live model is a reason-code-specific Logistic Regression model trained only on relevant evidence fields. Unknown fields are explicitly encoded as uncertainty rather than silently treated as positive evidence.

Rules and the HistGradientBoosting challenger are retained for offline comparison.

## Evaluation protocol

- train: `data/train.csv`
- model-selection / calibration: `data/dev.csv`
- final evaluation: `data/test.csv`
- no `would_win` value is supplied to the live scorer
- policy tuning is performed on development data only

## Current result

The bundled test snapshot is approximately PR-AUC `0.723`, with 75.9% precision and 40.1% recall at the current policy operating point.

## Known limitations

The data is synthetic and evidence-only. The public benchmark does not prove production fraud generalization. The graph layer is tested separately because the tabular dataset does not contain historical network identifiers.
