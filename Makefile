data:
	python scripts/generate_data.py --out-dir data

test:
	python -m pytest -q

benchmark:
	python scripts/benchmark.py

judge:
	python -m pytest -q
	python scripts/benchmark.py
	python scripts/judge_report.py

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
