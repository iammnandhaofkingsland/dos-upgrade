# Daily commands. Run from the repository root.
PY ?= python3
.PHONY: setup test run run-live seed shots adk-web eval deploy faults check

setup:            ## create the virtual environment and install everything
	$(PY) -m venv .venv && . .venv/bin/activate && pip install -r server/requirements-dev.txt
test:             ## offline tests: no key, no network, no cost
	cd server && DQ_MODEL_MODE=mock ../.venv/bin/python -m pytest -q
run:              ## run in simulation mode on http://localhost:8080
	cd server && DQ_MODEL_MODE=mock ../.venv/bin/uvicorn main:app --reload --port 8080
run-live:         ## run against Gemini (needs GOOGLE_API_KEY in server/.env)
	cd server && set -a && . ./.env && set +a && ../.venv/bin/uvicorn main:app --reload --port 8080
seed:             ## fill a running server with demo activity
	.venv/bin/python tools/seed_demo.py http://localhost:8080
shots:            ## screenshots of every console screen into ./shots
	.venv/bin/python tools/screenshots.py http://localhost:8080 shots
adk-web:          ## open the ADK developer UI on the six demo-ready agents
	cd server && PYTHONPATH=. ../.venv/bin/adk web adk_agents
eval:             ## run the ADK evaluation for LoanProcess
	cd server && PYTHONPATH=. ../.venv/bin/adk eval adk_agents/loanprocess evals/loanprocess.evalset.json --config_file_path=evals/eval_config.json --print_detailed_results
deploy:           ## build and deploy to Cloud Run
	bash infra/deploy.sh

faults:           ## fault matrix: every fault on every machine, 10 seeds, detection time and diagnosis
	cd server && PYTHONPATH=. ../.venv/bin/python ../tools/fault_matrix.py
check:            ## quick plain-English check of one build stage: make check STEP=foundation (config, data, tools, agents, safety, server, plant, all)
	cd server && PYTHONPATH=. ../.venv/bin/python ../tools/check_step.py $(STEP)
