# Contributing

1. Create a focused branch.
2. Run `pytest -q` before and after changes.
3. Run `python training/train_models.py` for ML changes.
4. Do not tune against `test.csv`; use `dev.csv` for experimentation.
5. Do not add external integrations without tests and explicit documentation of credential requirements.
6. Keep model inference advisory; final action must remain deterministic policy output.
