# RoleTailor evals

Two jobs: prove output quality and cost on real models before anyone uses the product,
and stop a prompt or model change from shipping if it makes things worse.

## What is in the set

35 synthetic but realistic resume and job pairs in `cases/`, one YAML file each. They
cover 15 role families (data and AI, software, product, design, marketing, sales,
finance, healthcare, education, operations, HR, legal, support, other engineering,
executive), every seniority level from intern to executive, and 16 scenarios, including
the ones most likely to produce invented content: missing credentials, seniority
stretches, keyword-bait job posts, prompt injection in the job or the resume, resumes
with no numbers, number-heavy resumes, sparse and long resumes, table layouts, and
non-ASCII text. Every person, company, and contact detail is fictional.

Each case lists `canaries`: things the job asks for that the resume does not show. A
canary in the output is a fabrication. `validate_cases.py` checks that every canary is
in the job text and absent from the resume (synonyms included), and that the resume
parses into editable experience bullets.

## Metrics

Computed in `evalkit/metrics.py` from the source resume and the final edits, without
trusting the pipeline's own validators:

| Metric | Meaning | Gate |
|---|---|---|
| fabrication | a canary or a new number appears in an edited block | zero, always |
| keyword coverage before and after | importance-weighted share of job keywords present | may not drop |
| expected gap recall | must-have gaps the plan reports to the user | live, 0.8 |
| changes, reverted blocks | accepted edits, and edits that failed every gate | per-case bounds |
| length drift | largest relative length change of an edited block (warn above 25%) | reported |
| unexpected terms | proper nouns in edits that occur nowhere in the resume | reported |
| cost and latency | per run and per stage, mean, p50, p95 | live: mean $0.05, p95 $0.08 |
| judge (live) | truthfulness, relevance, readability, voice, 1 to 5 | truthfulness 4.5 |

Errors (a provider outage, a crash) are counted separately and never as a model failure.

## Commands (from the repo root)

```bash
make setup             # once
make eval              # offline, deterministic, free
make eval-gate         # the CI gate: offline run compared with results/offline_baseline.json
make eval-live-quick   # 5 cases on real models, about $0.25, to check keys and wiring
make eval-live         # all cases, planning on Sonnet vs Haiku, with the judge; about $3, capped at MAX_USD
```

Live runs read `ANTHROPIC_API_KEY` (and `DEEPSEEK_API_KEY` for failover) from the
environment or from `.env` at the repo root. Never commit `.env`.

Each run writes `reports/<timestamp>/report.json` (full detail, including the edited text)
and `report.md` (the comparison table). `make eval-live` also writes
`results/live_summary.json`, a numbers-only summary that is committed.

## The regression gate

- Every pull request runs the offline gate. It fails on any fabrication, any failing case,
  a per-case drop in accepted changes or coverage, or an estimated cost increase above
  10%. Estimated cost tracks prompt length, so it catches prompt bloat.
- A pull request that changes `config/models.yaml`, a prompt, or a validation rule also
  needs live evidence: `results/live_summary.json` must carry the current behaviour
  fingerprint (a hash of those files) and meet the live thresholds in `gate.yaml` for the
  production configuration. Run `make eval-live` on the branch and commit the summary.
- The workflow can also run the live eval in CI (`Actions > evals > Run workflow`, tick
  `run_live`) once an `ANTHROPIC_API_KEY` repository secret exists.

When a change is meant to alter offline results, review the diff of
`results/offline_baseline.json` after `make eval-baseline` and commit it with the change.

## Limits worth knowing

- The offline provider only swaps listed synonyms, and its claim verifier rejects any new
  capitalised term, so offline runs accept few edits. Offline proves the plumbing, the
  safety gates, and prompt size; quality and real cost come from live runs.
- The judge defaults to Sonnet, which is also the production planner. Use
  `--judge-model claude-opus` for a judge that is independent of both configurations.
- Synthetic cases are a floor, not a ceiling. Add real (consented, anonymised) resumes as
  they come in, keeping personal data out of the repository.

## Adding a case

Copy a case close to what you want, change it, then run `make eval-validate` and
`make eval-baseline`. Keep canaries concrete (named tools, licences, certifications).
