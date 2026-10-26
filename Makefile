PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: install test app benchmark-fixture benchmark-live benchmark-dry-run analysis-dry-run

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

app:
	$(PYTHON) scripts/run_app.py --port 43123

benchmark-fixture:
	BEAM_PROVIDER=fixture $(PYTHON) scripts/run_benchmark.py --provider fixture --max-repos 2 --token-limits 120000,240000

benchmark-dry-run:
	$(PYTHON) scripts/run_benchmark.py --dry-run --max-repos 2 --token-limits 120000,240000,400000

benchmark-live:
	$(PYTHON) scripts/run_benchmark.py --max-repos 2 --token-limits 120000,240000,400000

analysis-dry-run:
	$(PYTHON) scripts/run_analysis.py https://github.com/pallets/flask --dry-run --token-limit 120000
