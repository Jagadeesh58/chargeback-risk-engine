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

regen:
	python scripts/benchmark.py
	python scripts/evaluate_hard_cases.py
	python scripts/oracle_ceiling.py
	python scripts/generate_report.py
	python scripts/robustness_benchmark.py

verify:
	python -m pytest -q
	python scripts/verify_release.py
	git diff --exit-code -- README.md artifacts docs ':!docs/*.png'

latency:
	python scripts/latency.py

demo:
	python scripts/demo.py

train:
	python training/train_models.py

api:
	uvicorn chargeback_risk_engine.api:app --reload

release-zip:
	git archive --format=zip --output=chargeback-risk-engine.zip HEAD

