# Common tasks. Run `make setup` once; everything else uses backend/.venv.
PY := backend/.venv/bin/python
EVAL := cd backend && .venv/bin/python ../evals

.PHONY: setup test eval eval-validate eval-gate eval-baseline eval-live eval-live-quick

setup:
	cd backend && (command -v uv >/dev/null && uv venv .venv && uv pip install -p .venv -e ".[dev]" \
	  || (python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"))

test:
	cd backend && .venv/bin/python -m pytest -q

eval-validate:
	$(EVAL)/validate_cases.py

# Offline, deterministic, free. Same as CI.
eval: eval-validate
	$(EVAL)/run_evals.py

eval-gate: eval-validate
	$(EVAL)/gate.py offline

eval-baseline:
	$(EVAL)/gate.py offline --update

# Real models. Needs ANTHROPIC_API_KEY in .env or the environment. About $3 for the
# full set (35 cases x 2 planning configs + judge); capped by MAX_USD.
MAX_USD ?= 6
eval-live:
	$(EVAL)/run_evals.py --live --yes --compare-plan --judge --save-summary --max-usd $(MAX_USD)

# Five cases, current config only, about $0.25. Use to check keys and wiring.
eval-live-quick:
	$(EVAL)/run_evals.py --live --yes --max-usd 1 --case ml_engineer_strong_match \
	  --case software_mobile_injection --case finance_senior_analyst_no_cpa \
	  --case civil_to_datasci_poor_match --case marketing_brand_manager_no_metrics
