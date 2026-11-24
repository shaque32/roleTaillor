# RoleTailor web frontend

Next.js 15 (App Router) + TypeScript (strict) + Tailwind CSS. Built against `docs/api-v1.md`.

## Running locally

```bash
cd frontend
cp .env.example .env.local   # adjust the API URL if needed
npm install
npm run dev                  # http://localhost:3000
```

The backend must be reachable at `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000/v1`).

| Script | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` / `npm start` | Production build / serve |
| `npm run lint` | `next lint` (eslint-config-next, core-web-vitals + typescript) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest unit tests (word-level diff utility) |

### Environment

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/v1` | Backend base URL. Inlined at build time. |
| `API_BASE_URL` | – | Runtime override (server side), handy in Docker. Takes precedence. |
| `COOKIE_SECURE` | `true` in production | Set `false` only when serving production builds over plain HTTP on a non-localhost host. |
| `ALLOWED_ORIGINS` | – | Comma-separated extra origins accepted on mutating requests (e.g. when a CDN rewrites `Host`). |

## Docker

```bash
docker build -t roletailor-web frontend
docker run -p 3000:3000 -e API_BASE_URL=http://api:8000/v1 roletailor-web
```

Multi-stage build, `output: "standalone"`, runs as a non-root `app` user.

## How auth works

The browser never sees the bearer token.

- `POST /api/session` `{action: "login" | "register", ...}` proxies to `/v1/auth/login|register` and stores the token in an
  `httpOnly`, `SameSite=Lax` cookie (`Secure` in production). `DELETE /api/session` logs out upstream and clears it.
- All other API calls go to `/api/proxy/<path>`, a same-origin route handler that attaches `Authorization: Bearer <token>`,
  forwards `Idempotency-Key`, `Content-Type` and `X-Correlation-ID`, and streams the response back. Mutating requests must
  carry a same-origin `Origin` (or `Sec-Fetch-Site: same-origin`), otherwise they get `403 forbidden_origin`.
- `middleware.ts` redirects to `/login` when no session cookie is present. A `401` from the API clears the cookie.

## Layout

```
app/(auth)/login, register         sign in / sign up
app/(focus)/onboarding             consent -> first resume -> first job
app/(app)/dashboard                workflows table, expandable detail, credit meter
app/(app)/resumes                  list, upload, rename, archive, versions/restore
app/(app)/resumes/new              guided builder -> POST /resumes/guided
app/(app)/resumes/[id]             extracted blocks + extraction findings
app/(app)/tailor/new               start a tailoring (402 / 422 handling)
app/(app)/tailor/[id]              progress polling, scores, simulation, gaps, change review, exports
app/(app)/applications             application tracker CRUD
app/(app)/settings                 profile, preferences, billing, consent, export, delete account
app/api/session, app/api/proxy     auth cookie + authenticated proxy
lib/types.ts, lib/api.ts           contract types and typed client
lib/diff.ts                        word-level LCS diff (unit tested)
components/ui                      Button, Input, Card, Badge, ScoreBar/Ring, DiffView, EmptyState, Toast, Dialog, ...
```

## API assumptions beyond the contract

Where `docs/api-v1.md` leaves shapes open, the UI follows `db/migrations/001_roletailor_schema.sql` and the backend
domain models, and tolerates missing optional fields:

- Errors: the `{error: {code, message, details}}` envelope; `402 payment_required`, `422 job_url_unreadable`,
  `428 consent_required` are matched on status and `error.code`.
- `GET /workflows/{id}`: `scores_before` is `{ats, job_alignment, keyword_relevance, formatting}`; `latest` carries
  `ats_score`, `job_alignment_score`, `keyword_relevance_score`, `formatting_score`, `simulation_score`, `approved_at`,
  `iteration`; `gaps` is `string[]` (objects `{term, importance}` also accepted); `feedback` matches
  `HiringManagerFeedback`; `changes[]` are `resume_changes` rows with `id`. Optional `workflow.stage`,
  `workflow.recovery_message` / `workflow.error.message`, `workflow.target_role` and `workflow.company` are used when present.
- Iterations: `focus_block_ids` are the changes' `block_path` values.
- Resume version `findings` items are `{code, detail, severity?, block_id?}`; `blocks` match `documents.model.Block`.
- Guided builder items: experience `{company, title, location, start, end, bullets[]}`, education
  `{institution, degree, field, start, end, details}`, certifications `{name, issuer, date}`, projects
  `{name, link, description, bullets[]}`, summary/skills/other `{text}`; contact matches `Contact`.
- Applications: `GET/POST /applications`, `PATCH/DELETE /applications/{id}`; statuses from the DB check constraint.
- Billing: active subscription is `subscription.status === "active"`. Checkout opens `checkout_url`; after paying, the
  user returns and the UI resends `POST /workflows` with `accept_paid_usage: true` and a fresh `Idempotency-Key`.
- Preference enums (`resume_tone`, `ats_preference`, `technical_depth`) are free text in the DB; the UI offers
  `professional|confident|concise|warm`, `balanced|ats_first|human_first`, `low|medium|high`.
- Consent `policy_version` is `2026-11` (`lib/api.ts`). Share links use `expires_in_hours: 72` on a fresh PDF export.
