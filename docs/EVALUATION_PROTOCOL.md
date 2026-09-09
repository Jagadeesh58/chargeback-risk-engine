# Evaluation Protocol

1. Train candidate models on `train.csv`.
2. Compare model candidates on `dev.csv`.
3. Fit calibration only on development data.
4. Tune the policy threshold on `dev.csv` under explicit precision/volume constraints.
5. Freeze the selected configuration.
6. Run `test.csv` exactly once for final reporting.
7. Report both expected economics and realized synthetic outcomes.
8. Report per-reason metrics and bootstrap uncertainty.
9. Run the frozen hard-case suite independently.

The final report must never silently replace one ablation with another or use test outcomes to tune a threshold.
