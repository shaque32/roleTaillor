# RoleTailor

RoleTailor tailors a resume to a job description. It keeps the original DOCX formatting exactly and never invents facts.

- **Format preserving.** Resumes are parsed into text blocks. Edits are applied at the DOCX XML run level, so fonts, spacing, tabs, bullets and section order stay as they were. A rendered page check keeps the result within the page limit.
- **Fact grounded.** Every rewrite passes deterministic gates and a claim check. These catch new numbers, new tools, unsupported job keywords, inflated scope, stuffing and generic phrasing. A rewrite that fails is retried, then escalated to a stronger model, then dropped in favour of the original text.
- **Cheap to run.** A staged pipeline gives each step to the cheapest model that holds quality. Routing, failover and prices live in `config/models.yaml`. The estimated cost is about $0.04 per generation, and about $0.01 if planning also moves to the low tier. See [docs/architecture.md](docs/architecture.md).

## Layout
```
backend/roletailor/
  documents/     DOCX/PDF parsing, run-preserving edits, PDF conversion, templates
  ai/            gateway, router, providers (Claude, DeepSeek/OpenAI-compatible, offline fake), prompts, cache
  pipeline/      stages, orchestrator, validation gates, scoring, heuristics
  api/ services/ FastAPI routes and deterministic services (auth, billing, storage, review)
  worker/        Celery task that runs the pipeline and persists results
frontend/        Next.js 15 + TypeScript + Tailwind
db/              SQL migrations (001 is the source-of-truth schema) and runner
config/          models.yaml: model tiers, per-stage routing, prices, prompt pins
evals/           eval cases and harness
docs/            architecture, API contract
```

## Run locally
```bash
cp .env.example .env            # add ANTHROPIC_API_KEY (and DEEPSEEK_API_KEY for failover)
docker compose up --build       # postgres+pgvector, redis, migrate, api :8000, worker, web :3000
```
To run without API keys, set `RT_LLM_MODE=fake`. This uses a deterministic offline provider that runs the whole pipeline.

Without Docker:
```bash
cd backend && uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"
python ../db/migrate.py                         # as the schema owner (RT_MIGRATION_DATABASE_URL)
uvicorn roletailor.main:create_app --factory --port 8000
celery -A roletailor.worker.celery_app worker -l info
cd ../frontend && npm install && npm run dev
```

## Deploy
Cloud deployment (Fly.io, Tigris storage, managed Postgres, CI/CD) is described in [docs/deploy.md](docs/deploy.md).

## Keeping keys out of the repo
- Real keys go only in `.env` (ignored by git) locally and in `fly secrets` in the cloud. `.env.example` is a template and must never hold a real value.
- CI runs gitleaks over the full git history on every push and PR, and fails on any match. It also fails if an env file other than `.env.example` is tracked.
- Optional local guard: `pip install pre-commit && pre-commit install` blocks a commit that contains a key.
- Logs and eval reports pass through `roletailor.redaction.redact`, which masks key values before they are written.
- If a key is ever committed, rotate it in the provider console first. Removing it from git does not make it safe again.

## Test and evaluate
```bash
make setup             # once: backend/.venv with dev dependencies
make test              # pytest; platform tests need local Postgres
make eval-gate         # offline eval (35 cases) compared with the committed baseline; same as CI
make eval-live-quick   # 5 cases on real models, about $0.25
make eval-live         # all cases, planning on Sonnet vs Haiku, with an LLM judge; about $3
```
Any canary term (a job requirement the resume does not show) or new number in the output fails the case. See `evals/README.md` for the case set, metrics, thresholds, and the CI gate.

## Changing models or prompts
- To change a model or a stage's tier, edit `config/models.yaml`, run `make eval-live`, and commit `evals/results/live_summary.json` with the change. CI blocks prompt, model, and validation changes without a live summary from the same code.
- To change a prompt, add `backend/roletailor/ai/prompts/<stage>.v<N+1>.md`. Never edit a shipped version. To roll back, pin the previous version under `prompt_pins`.
- Each model call writes one `ai_metrics` row with the model, prompt version, routing reason, tokens, cost and latency.
- Dashboards and alerts on cost, latency, errors and fabrication attempts: see `docs/monitoring.md` and `docs/runbooks/ai-alerts.md`.
