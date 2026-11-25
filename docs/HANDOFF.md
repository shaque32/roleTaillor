# RoleTailor handoff packet

**For:** arshNY, who owns the accounts and secrets setup.
**From:** Arsh.
**Status date:** 25 November 2026.

This packet explains what RoleTailor is, what has been built and why, how to see the MVP on your own machine, and the exact accounts and secrets work that is left. It contains names of secrets only. No real value appears here, and none should ever be pasted into a chat, an issue, a PR or a commit.

## 1. What RoleTailor is

RoleTailor tailors an uploaded resume to a job description. The user uploads a resume (DOCX, PDF, a scan, or pasted text), adds a job (pasted text or a job posting URL), and gets a tailored version with every change shown for review, a keyword and ATS comparison, a simulated hiring manager view, and an export.

Three design commitments shape everything:

- **It never invents facts.** Every rewrite is checked by code against the original resume. A rewrite that fails is retried and then dropped in favour of the original text.
- **It keeps the original formatting.** Edits are applied inside the original DOCX or PDF, so fonts, spacing and layout stay as they were.
- **It is cheap to run.** Each step uses the cheapest model that holds quality. A tailoring costs about $0.025 in model spend.

### Product status

| Area | Status |
|---|---|
| MVP feature set | Built and merged to `main`. Runs end to end locally with Docker. |
| Quality proof | Final live eval passed: 0 fabrications in 70 runs (see section 3). |
| Security | Pre-launch audit done. No critical findings. All 9 high findings fixed and merged (PR #11). |
| Cloud deployment | Configuration, scripts and CI/CD are written for Fly.io. **Nothing is deployed yet.** It waits on the accounts and secrets in section 5. |
| Payments | Stripe integration built and tested against a mock. No Stripe account is connected yet. |
| Email | Verification and password reset built (PR #12, open). No Resend account is connected yet. |
| Open work | Three open PRs and three follow-ups (section 6). |

The short version: the software is ready, and the path to a live staging site is the checklist in section 5.

## 2. What was built and why

| What | Why it was built this way |
|---|---|
| **Staged pipeline, not one large prompt.** Parse resume, analyze job, plan, write summary, rewrite bullets in parallel, validate, check page length, score, feedback. | A single call to a top model is expensive, hard to audit and hard to keep truthful. Stages let each step use a cheaper model, cache what does not change (the parsed resume and the parsed job), and be tested on its own. Plain Python orchestrates the stages. There is no free-running agent at serving time. |
| **A model per stage.** Claude Haiku 5.5 for parsing, bullet rewrites, claim checks and feedback. Claude Sonnet 5.5 for the plan and the summary. DeepSeek as failover in each tier. All routing and prices live in `config/models.yaml`. | The live eval showed planning on Sonnet passes 94% of cases against 77% on Haiku, so Sonnet earns its cost there. The summary is the first thing a recruiter reads, so it also gets Sonnet. Everything else holds quality on Haiku. Changing a model is a config change that the eval gate must approve. |
| **No-fabrication gates.** Deterministic rules block new numbers, new tools or proper nouns, unsupported job keywords, keyword stuffing, generic phrasing and length drift. A model claim check catches inflated scope. | Truthfulness is enforced by code, not by asking the model nicely. A generation degrades to fewer changes, never to invented ones. Every outcome is stored in `validation_results`. |
| **DOCX and PDF edited in place, plus OCR for scans.** | Users care about keeping their layout. DOCX edits are made at the XML run level. Text PDFs are edited in the content stream on the original baselines and fonts. Scanned PDFs are read with Tesseract and rendered through an ATS template. No AGPL libraries are used, because this is a commercial product. |
| **Paste a resume.** | Removes the upload barrier for people who do not have a file to hand. |
| **Stripe billing.** $9.99 a month subscription, an optional $0.50 single resume price, the customer portal, and signed, deduplicated webhooks. | Model cost is under 10% of revenue per tailoring, even on pay per use. |
| **Monitoring.** Prometheus metrics and alerts, two Grafana dashboards, and SQL ops views for cost, latency, errors and fabrication attempts. | Cost and quality need to be observable from the first day of live traffic. Every model call writes one `ai_metrics` row with model, prompt version, tokens, cost and latency. |
| **Evals and a CI gate.** 35 synthetic cases across 15 role families and 16 scenarios, an offline gate on every PR, and a live eval that must accompany any prompt, model or validation change. | A prompt or model change cannot ship if it makes output worse or more expensive. |
| **Redesign of the web app.** Every screen was redesigned for ease of use on desktop and mobile. AI consent is asked at the first tailoring, not as the first onboarding screen. | The first version worked but was hard to follow. The audit is in `docs/ux-audit.md`. |
| **Job board fetch.** A job URL from Greenhouse, Lever, Ashby or SmartRecruiters is read through the board's public posting API. Other URLs use a generic page reader, and paste is always the fallback. | Most users have a link, not the text. All fetches go through SSRF guards. |
| **Security audit and fixes.** Per-visitor rate limits, request body caps, sandboxed file parsing, SSRF connection pinning, a production config guard, secret scanning in CI and log redaction. | Done before launch so that the first deploy is the hardened one. |

Supporting documents in the repo: `README.md`, `docs/architecture.md`, `docs/deploy.md`, `docs/stripe-setup.md`, `docs/monitoring.md`, `docs/runbooks/ai-alerts.md`, `evals/README.md`, and `docs/email-setup.md` once PR #12 merges.

## 3. Key numbers from the final live eval

Run on 25 November 2026: 35 cases on each of two planning configurations, 70 runs in total, on real models.

| Measure | Result | Bar |
|---|---|---|
| Fabrications | **0 in 70 runs** | 0, a hard gate that is never relaxed |
| Pass rate (production config, Sonnet planning) | **94%** | 85% |
| Model cost per tailoring | **$0.025** mean, $0.035 at p95 | $0.05 mean, $0.08 at p95 |
| Judge truthfulness (1 to 5) | **4.37** | 4.25 for now |
| Run time | 36 s at p50, 46 s at p95 | |

Two notes on reading these:

- **The truthfulness bar is relaxed on purpose.** The original bar was 4.5. Arsh approved 4.25 for v1 because the LLM judge is not yet calibrated against human ratings, and what it flagged was wording that implies ownership, not invented facts. The bar goes back to 4.5 once the gold set shows the judge is calibrated on 10 or more human-rated real cases. The setting and its reason are in `evals/gate.yaml`.
- **Haiku planning was tested and rejected.** It cost $0.010 a run but passed only 77% of cases and made no edits in 34% of runs.

The committed summary is `evals/results/live_summary.json`.

## 4. How to see the MVP

You need Docker Desktop and the repo. It has been run on an Apple Silicon Mac.

```bash
git clone https://github.com/shaque32/roleTailor.git
cd roleTailor
cp .env.example .env
docker compose up --build
```

Then open **http://localhost:3000**, register, upload or paste a resume, add a job, and run a tailoring.

### Fake mode or live mode

| Mode | Setting in `.env` | What you get |
|---|---|---|
| Fake | `RT_LLM_MODE=fake` | No keys and no cost. A deterministic offline provider runs the whole pipeline. Good for seeing the product flow. It accepts few edits, so it does not show real writing quality. |
| Live | `RT_LLM_MODE=live` and `ANTHROPIC_API_KEY` set (`DEEPSEEK_API_KEY` optional, for failover) | Real tailoring at about $0.025 a run. |

`.env` is ignored by git. Never commit it.

### Where things are locally

| What | Address |
|---|---|
| Web app | http://localhost:3000 |
| API | http://localhost:8000 (`/readyz` for health) |
| Grafana dashboards | http://localhost:3001, user `admin`, password from `GRAFANA_ADMIN_PASSWORD` in `.env` |
| Prometheus (alerts and targets) | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |

The dashboards need the monitoring overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up
```

Grafana has two dashboards: "AI overview" (live metrics) and "AI quality and cost (SQL)". Run a few tailorings first so they have data.

Local behaviour to know:

- Stripe is not needed to look around. Billing screens work once the Stripe test values are in `.env` (see `docs/stripe-setup.md`, section 5, for `stripe listen`).
- After PR #12 merges, a new account must confirm its email before tailoring. Locally no email is sent. The link is printed in the API log: `docker compose logs api | grep "token="`.
- To see the screens with no backend at all, `frontend/dev/README.md` describes a mock API with demo data.

## 5. Accounts and secrets checklist

Work top to bottom. Do **staging first**, then repeat for production. The full runbook is `docs/deploy.md`. Where a script generates a secret, you never see or handle the value.

Rules for every step:

- Real values go only into `fly secrets`, GitHub secrets, your local `.env`, and your password manager.
- Never paste a value into a chat, PR, issue or commit. CI runs gitleaks on every push and fails on a match.
- If a key is ever exposed, rotate it in the provider console first. Deleting it from git does not make it safe.

### 5.1 GitHub access

- [ ] Ask the repo owner (`shaque32`) to add `arshNY` as a collaborator on `shaque32/roleTailor`. Today `arshNY` has no access, so PRs cannot be assigned to or reviewed by that login.
- [ ] Confirm CodeRabbit is still installed on the repo. It auto-reviews PRs that target `main` and are not drafts. On a draft, comment `@coderabbitai review` to trigger it.
- [ ] Install the Claude GitHub App on the repo: <https://github.com/apps/claude/installations/select_target>. Without it, PR events do not reach the Claude threads that maintain the PRs.
- [ ] Optional, for running the paid live eval in CI: add repository secrets `ANTHROPIC_API_KEY` and `DEEPSEEK_API_KEY` (Settings, Secrets and variables, Actions). The offline gate needs no secrets.

### 5.2 Model providers

- [ ] Anthropic: create an API key in the Anthropic Console and set a monthly spend limit. Secret name: `ANTHROPIC_API_KEY`. Use separate keys for local, staging and production.
- [ ] Optional, DeepSeek: create an API key for failover. Secret name: `DEEPSEEK_API_KEY`. Without it the product runs on Claude only and has no failover provider.

### 5.3 Domain

- [ ] Choose the domain and three hostnames: the web app (`app.<domain>`), the API (`api.<domain>`), and a mail subdomain (`mail.<domain>`). Staging uses `app-staging` and `api-staging`.
- [ ] Replace the `roletailor.example` placeholders in `deploy/fly/env/<env>.api.env` and `deploy/fly/env/<env>.web.env`. These files are not secret and are committed. The API refuses to start in production with placeholder or localhost URLs.

### 5.4 Fly.io

Estimated cost: about $60 a month for production and $20 for staging, before model spend.

- [ ] Create a Fly.io account with billing, install `flyctl`, and run `fly auth login`.
- [ ] Create the Postgres cluster (Fly Managed Postgres, version 16, which ships pgvector). Developer plan for staging, Basic for production.
- [ ] Create the database roles as the cluster admin: `psql "$ADMIN_URL" -v owner_password=... -v app_password=... -f db/bootstrap/managed_roles.sql`. This creates `rt_owner` (runs migrations) and `rt_app` (the app, bound by row-level security). Generate both passwords with `openssl rand -hex 24` and keep them in your password manager. `rt_app` must never be a superuser, own the database, or have BYPASSRLS. The API health check fails if it does.
- [ ] Run `deploy/fly/bootstrap.sh staging`. It creates the three apps (`roletailor-api-staging`, `roletailor-web-staging`, `roletailor-redis-staging`), the Redis volume and the Tigris bucket, and it generates and stores these without showing them:
  - `REDIS_PASSWORD` (Redis app) and `RT_REDIS_URL` (API app)
  - `RT_SECRET_KEY` (API app)
  - `RT_PROXY_SHARED_SECRET` (API app) and `API_PROXY_SECRET` (web app). This pair is new from PR #11. It is one value held by both apps, and it lets the API trust the visitor address the web app relays, so rate limits apply per visitor. Outside dev the API refuses to start without it. To rotate, set both to one new value.
  - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3`, `BUCKET_NAME` (set by Tigris)
- [ ] When the script prompts, paste `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY` and the three Stripe values from 5.5. Input is hidden. A blank answer skips that secret, and you can run the script again later.
- [ ] Set the two database URLs on the API app with `fly secrets set --stage`:
  - `RT_DATABASE_URL`: the **pooled** connection as `rt_app`, scheme `postgresql+psycopg://`
  - `RT_MIGRATION_DATABASE_URL`: the **direct** connection as `rt_owner`. It must not go through a transaction pooler, because the migration runner holds an advisory lock.
- [ ] Deploy: `deploy/fly/deploy.sh staging redis` once, then `deploy/fly/deploy.sh staging`.
- [ ] Add certificates and DNS: `fly certs add <host> -a <app>` for the API and web hostnames, then create the DNS records Fly prints.
- [ ] Wire up CI: in GitHub, Settings, Environments, create `staging` and `prod`. Give each a `FLY_API_TOKEN` secret (`fly tokens create deploy`) and an `API_URL` variable. Add a required reviewer on `prod`. After this, every merge to `main` deploys staging, and production deploys are manual with approval.
- [ ] Smoke test: `curl https://api-staging.<domain>/readyz` returns `ready`. Then register, upload a resume and run one tailoring.

Optional secret: `RT_METRICS_TOKEN`. Leave it unset if you use Fly's managed metrics scraping, because the scraper sends no token.

### 5.5 Stripe (test mode first)

Full steps: `docs/stripe-setup.md`. Do everything in test mode for staging. Repeat in live mode only for production, after the going-live checklist in that document passes.

- [ ] Create the product "RoleTailor Pro" with a recurring price of **$9.99 USD a month**. The price id goes in `RT_STRIPE_SUBSCRIPTION_PRICE_ID`.
- [ ] Optional: a one-time $0.50 price for a single resume, in `RT_STRIPE_PAY_PER_USE_PRICE_ID`.
- [ ] Configure the customer portal: allow cancel at period end, payment method updates and invoice history. Leave plan switching off.
- [ ] Copy the secret key into `RT_STRIPE_SECRET_KEY`. It never goes in the frontend.
- [ ] Add a webhook endpoint at `https://<api-host>/v1/billing/webhook` with exactly these events:
  - `checkout.session.completed`
  - `checkout.session.async_payment_succeeded`
  - `checkout.session.async_payment_failed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.paid`
  - `invoice.payment_succeeded`
  - `invoice.payment_failed`
  - `charge.refunded`
- [ ] Copy the endpoint's signing secret into `RT_STRIPE_WEBHOOK_SECRET`.
- [ ] Set the values on the API app (through `bootstrap.sh` or `fly secrets set`) and test: subscribe with card `4242 4242 4242 4242`, confirm Settings shows the subscription as active, then cancel in the portal.

Prices, the portal configuration and the webhook endpoint are separate in test mode and live mode. Each must be created twice.

### 5.6 Resend (email), needed once PR #12 merges

Full steps: `docs/email-setup.md` in PR #12. About 15 minutes plus DNS propagation.

**Staging needs this too, not only production.** Once PR #12 is merged, the API refuses to start outside local development unless `RT_EMAIL_PROVIDER` is `resend`, `RESEND_API_KEY` is set, and `RT_EMAIL_FROM` is a real sender. The console provider, which prints emails to the log, works on a local machine only. Do this section before the first staging deploy that includes PR #12.

- [ ] Create a Resend account.
- [ ] Add the sending subdomain (`mail.<domain>`) and create the DNS records Resend shows: DKIM, SPF and MX. Add a DMARC record if the domain has none.
- [ ] Wait for the domain to show "Verified". Keep open and click tracking off, because click tracking would rewrite the one-time links.
- [ ] Create an API key with "Sending access" only, restricted to that domain. One key for staging and one for production. Secret name: `RESEND_API_KEY`, set on both `roletailor-api-staging` and `roletailor-api`.
- [ ] Set `RT_EMAIL_FROM` in `deploy/fly/env/<env>.api.env` to a sender on the verified domain. Do this in both `staging.api.env` and `prod.api.env`. This is not secret. The API refuses to start on staging or production while it is still the `.example` placeholder.
- [ ] Test: register with a real address, confirm it from the email, then run "Forgot password?".

### 5.7 Alert channel

Alerts are defined and tested, but the receivers do nothing until a channel is connected. Real notification delivery has not been verified yet.

- [ ] Choose one channel: a Slack incoming webhook, an email (SMTP) account, or PagerDuty.
- [ ] Uncomment the matching example in `ops/monitoring/alertmanager/alertmanager.yml` for the `warning` and `critical` receivers.
- [ ] Put the webhook URL, SMTP password or routing key in a file that Alertmanager mounts (for example `/etc/alertmanager/slack_webhook_url`). It never goes in git.
- [ ] Decide where monitoring runs in the cloud: Fly's managed Prometheus and Grafana (fly-metrics.net), Grafana Cloud, or the self-hosted overlay. `docs/monitoring.md` covers each.
- [ ] Review the daily model spend budget ($50, in `ops/monitoring/prometheus/rules/recording.yml`) and the thresholds after the first weeks of live traffic.

### 5.8 Database migrations

Migrations run automatically. On Fly, each API release runs `python db/migrate.py` before any new machine starts, and a failed migration stops the deploy while the old version keeps serving. Locally, `docker compose up` runs them. They are forward only.

| Migration | Adds | Where |
|---|---|---|
| 001 to 003 | Core schema with row-level security, the app role, public lookups | `main` |
| 004 | `roletailor_ops` schema: the monitoring views | `main` |
| 005 | Accept and reject analytics per change, and the summary stage in the ops views | `main` |
| 006 | Resume retention and purge | PR #13 |
| 007 | Email verification and reset tokens | PR #12 |
| 008 | Background OCR status on resumes | PR #14 |

- [ ] After the first deploy, confirm 001 to 005 are recorded in `public.schema_migrations`.
- [ ] For the Grafana SQL dashboard, create the read-only role `rt_metrics` once on the managed cluster. `managed_roles.sql` does not create it, and migration 004 skips its grants when the role is missing. The four statements are in `docs/monitoring.md` under "Run locally". Run them after the first deploy, and keep the role read only.
- [ ] As PRs #12, #13 and #14 merge, confirm 006, 007 and 008 apply on the next staging deploy. The runner tracks migrations by number, so two files must never share a number.

### Secret names at a glance

| Name | Lives on | Source |
|---|---|---|
| `ANTHROPIC_API_KEY` | API app, local `.env`, optional GitHub secret | Anthropic Console |
| `DEEPSEEK_API_KEY` (optional) | API app, local `.env`, optional GitHub secret | DeepSeek console |
| `RT_DATABASE_URL` | API app | You, pooled, as `rt_app` |
| `RT_MIGRATION_DATABASE_URL` | API app | You, direct, as `rt_owner` |
| `RT_REDIS_URL`, `REDIS_PASSWORD` | API app, Redis app | Generated by `bootstrap.sh` |
| `RT_SECRET_KEY` | API app | Generated by `bootstrap.sh` |
| `RT_PROXY_SHARED_SECRET`, `API_PROXY_SECRET` | API app, web app (same value) | Generated by `bootstrap.sh` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3`, `BUCKET_NAME` | API app | Set by Tigris through `bootstrap.sh` |
| `RT_STRIPE_SECRET_KEY`, `RT_STRIPE_WEBHOOK_SECRET`, `RT_STRIPE_SUBSCRIPTION_PRICE_ID`, `RT_STRIPE_PAY_PER_USE_PRICE_ID` (optional) | API app | Stripe dashboard |
| `RESEND_API_KEY` | API app, staging and production (one key each) | Resend dashboard |
| `RT_METRICS_TOKEN` (optional) | API app | You |
| `FLY_API_TOKEN` | GitHub environments `staging` and `prod` | `fly tokens create deploy` |
| Alert webhook URL, SMTP password or routing key | A file mounted into Alertmanager | Slack, your mail provider or PagerDuty |

## 6. Open PRs and what is left

### Open pull requests (all target `main`)

| PR | What it does | State | What it needs from you |
|---|---|---|---|
| [#12](https://github.com/shaque32/roleTailor/pull/12) Email verification and password reset | Confirmation link at sign-up, forgot password, and a password changed notice, through Resend. Tailoring needs a confirmed address. | Ready for review | The Resend account, a key for staging and a key for production, and `RT_EMAIL_FROM` in both env files (5.6). Migration 007. |
| [#13](https://github.com/shaque32/roleTailor/pull/13) Retention and caps | Erases a deleted resume 30 days after deletion with a nightly job. Makes the caps (60 runs a day, 15 iterations) configurable per plan with `RT_PLAN_LIMITS`. | Draft | Nothing required. Optional settings `RT_RESUME_RETENTION_DAYS` and `RT_PLAN_LIMITS`. Migration 006. |
| [#14](https://github.com/shaque32/roleTailor/pull/14) Background OCR | Moves reading of scanned PDFs out of the upload request into the worker, with a progress state and retry in the app. | Draft | Nothing required. Deploy the worker and API together. Migration 008. |

### Follow-ups after those

- **Gold set.** Arsh supplies 15 to 20 real resume and job pairs (kept local, never committed). Run `make eval-gold`, rate the results, then `make eval-gold-calibrate`. Once the judge is calibrated on 10 or more rated cases, restore the truthfulness bar to 4.5 in `evals/gate.yaml`.
- **Live job board smoke test.** The Greenhouse, Lever, Ashby and SmartRecruiters handlers are tested against recorded shapes, not live. Run once from a machine with open internet: `RT_LIVE_JOB_BOARDS=1 pytest tests/platform/test_job_boards.py -m live` in `backend/`.
- **First real deploy.** Nothing has run on Fly yet. The edge header behaviour behind the per-visitor rate limits, real alert delivery and a real Resend send all get their first proof on staging.
- **Open medium items from the security audit.** Consent withdrawal purge, password confirmation on account delete, further prompt-injection gates, a hashed lock file and pinned CI actions, and a real malware scanner for uploads.

### Known limits to be aware of

- The fabrication alert measures attempts the gates caught, not fabrications that escaped. Escaped ones need human review of sampled outputs, which is what the gold set and the logged accept and reject decisions are for.
- Two eval cases still get no edits on the production config (a legal role with a missing credential, and a support to customer success career change). The product declines to edit there, which is the safe direction.
- Job URLs from Workday, LinkedIn and Greenhouse on custom domains are not covered by a board handler. Paste is the fallback.
- A PDF edit that needs an extra line is reverted, because there is no reflow of later lines yet.
