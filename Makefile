test:
	python -m pytest -q

demo:
	python scripts/demo.py

train:
	python training/train_models.py

benchmark:
	python scripts/benchmark.py

api:
	uvicorn apps.api:app --reload

dashboard:
	streamlit run apps/dashboard.py
