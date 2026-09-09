data:
	python scripts/generate_data.py --out-dir data

test:
	python -m pytest -q

benchmark:
	python scripts/benchmark.py

policy-optimize:
	python -m chargeback_risk_engine.policy_optimizer

hard-cases:
	python scripts/evaluate_hard_cases.py

stress:
	python scripts/stress_benchmark.py

verify:
	python -m pytest -q
	python -m chargeback_risk_engine.policy_optimizer
	python scripts/benchmark.py
	python scripts/evaluate_hard_cases.py
	python scripts/verify_release.py
	python scripts/generate_report.py

latency:
	python scripts/latency.py

demo:
	python scripts/demo.py

train:
	python training/train_models.py

api:
	uvicorn apps.api:app --reload

dashboard:
	streamlit run apps/app_deployed.py
