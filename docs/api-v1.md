# RoleTailor API v1 (contract)

All routes are under `/v1`, JSON unless noted, and documented live at `/docs` (OpenAPI).
Auth is an opaque bearer session token (`Authorization: Bearer <token>`), stored hashed in
`sessions`. Every request carries or receives an `X-Correlation-ID`. Errors use
`{"error": {"code": "...", "message": "...", "details": {...}}}`.
Optional `X-Organization-ID` selects one of the user's organizations (default: the oldest).
Rate-limited routes (auth, workflow creation, iterations) return `429 rate_limited` with
`Retry-After`. Creates return 201 unless noted.

## Auth and profile
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /auth/register | `{email, password, full_name}` | `{token, expires_at, user, organization}` (password >= 10 chars) |
| POST | /auth/login | `{email, password, device_label?}` | `{token, expires_at, user, organization}`; `organization` is `{id, name, role}` |
| POST | /auth/logout | | 204 |
| POST | /auth/verify-email | `{token}` | `{status: "verified"}`; 400 `invalid_token` for a bad, expired or used link |
| POST | /auth/verify-email/resend | | 202 `{status: "sent"}` or 200 `{status: "already_verified"}`; needs a session; 503 `email_unavailable` if the provider is down |
| POST | /auth/forgot-password | `{email}` | always 202 `{status: "accepted"}`, whether or not the address has an account |
| POST | /auth/reset-password | `{token, password}` | `{status: "password_reset"}`; revokes every session of the user; 400 `invalid_token`, 422 `weak_password` |
| GET | /me | | `user` (profile + preferences + `consents: {ai_processing: bool}`) |
| PATCH | /me | any of `full_name, address, contact_number, linkedin_url, preferred_page_limit, industry_focus, resume_tone, ats_preference, technical_depth, preferred_template_id` | `user` |
| DELETE | /me | | 202 (right to delete) |
| GET | /me/export | | JSON data export |
| POST | /consents | `{purpose: "ai_processing", policy_version, granted}` | consent row |
| GET | /notifications | | `[{id, kind, payload, created_at, read_at}]` (in-app, e.g. `billing.payment_failed`) |
| POST | /notifications/{id}/read | | notification |

AI routes return `428 consent_required` until the user grants `ai_processing` consent.
They return `403 email_unverified` until the address is confirmed (`user.email_verified_at` is set);
`RT_REQUIRE_VERIFIED_EMAIL=false` turns that off. Emailed links carry the token in the URL fragment:
`{app}/verify-email#token=...` and `{app}/reset-password#token=...`.

## Resumes
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /resumes | | `[{id, name, origin, created_at, latest_version}]` |
| POST | /resumes | multipart `file` (DOCX/PDF), `name` | `{resume, version}` where version has `blocks`, `findings`, `layout_metadata` |
| POST | /resumes/text | `{text, name?}` | `{resume, version}`. Pasted plain text (at least 200 non-whitespace characters, at most 50,000 characters in total; `422 resume_text_too_short`, `413 resume_text_too_long`). No source file is stored (`source_file_id` null); the version has `source_format: "text"` and `t{n}` block ids, and exports render through the structured ATS template |
| POST | /resumes/guided | `{name, contact, sections:[{kind, title, items:[...]}]}` | `{resume, version}`. `contact` is the `Contact` model (`full_name` required). Items by section kind: experience `{company,title,location,start,end,bullets[]}`, education `{institution,degree,field,start,end,details}`, certifications `{name,issuer,date}`, projects `{name,link,description,bullets[]}`, anything else `{text}` (a bare string is accepted as `{text}`). The form is rendered to DOCX and re-parsed, so version blocks use DOCX ids (`p{n}`) |
| GET | /resumes/{id} | | resume with `versions[]` |
| PATCH | /resumes/{id} | `{name}` | resume |
| DELETE | /resumes/{id} | | 204 (archives) |
| GET | /resumes/{id}/versions/{vid} | | version |
| POST | /resumes/{id}/versions/{vid}/restore | | new version copied from `vid` |

## Jobs
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /jobs | `{source_url?, description?, title?, company?}` | job posting `{id, source_url, title, company, description, created_at}`. A pasted `description` wins over `source_url`. Greenhouse, Lever, Ashby and SmartRecruiters URLs are read through each board's public posting data; other URLs use a plain page fetch. URL fetch failure returns `422 job_url_unreadable` so the UI asks for a paste |
| GET | /jobs/{id} | | job posting |

## Tailoring workflows
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /workflows | `{resume_version_id, job_posting_id, page_limit?, accept_paid_usage?}` + `Idempotency-Key` header | `202 workflow`. Replaying a key returns the same workflow; reusing it for a different resume/job is `409 idempotency_conflict`. `402 payment_required` with details `{options:[{mode, amount_minor, currency, interval?}], free_used, free_limit, pay_per_use_credits, requires_paid_usage_acceptance}` when free quota is used up and no subscription; when a credit exists but was not accepted, resend with `accept_paid_usage: true` |
| GET | /workflows | | dashboard rows `{id, status, resume_name, target_role, company, ats_score, simulation_score, created_at}` |
| GET | /workflows/{id} | | `{workflow, latest, scores_before, gaps, positioning, feedback, changes[]}`. `workflow` adds `target_role`, `company`, `recovery_message` (failed/retrying) and `draft_state`; `latest` is the generated_resumes row (`*_score`, `iteration`, `approved_at`, `simulated_feedback`) or null; `scores_before` is `{ats, job_alignment, keyword_relevance, formatting}`; `feedback` is HiringManagerFeedback plus `label` (or null); `changes[]` are resume_changes rows of `latest` |
| POST | /workflows/{id}/iterations | `{focus_block_ids?, instructions?}` | `202 workflow`. Needs a completed (or failed) workflow with a generation; builds on the latest output. Same role, no credit consumed. `instructions` is recorded but not yet used by the pipeline |
| POST | /workflows/{id}/pause, /resume, /cancel | | workflow. Pause: draft/queued only. Resume: paused or failed (retries the pending run). Cancel: anything not completed |

Workflow `status`: draft, queued, running, paused, completed, failed, cancelled. Poll `GET /workflows/{id}` every 2 seconds while queued or running.

## Review and export
| Method | Path | Body | Returns |
|---|---|---|---|
| PATCH | /generated/{gid}/changes/{cid} | `{decision: accepted|rejected|pending}` | change |
| POST | /generated/{gid}/approve | | generated resume |
| POST | /generated/{gid}/exports | `{kind: docx|pdf|ats_report|feedback_report}` | `{export_id, download_url, expires_at}` |
| POST | /exports/{eid}/share | `{expires_in_hours}` (1..720) | `{url, expires_at}` |
| GET | /share/{token} | public | 302 to a short-lived signed download URL; 404 when expired or revoked |
| GET | /files/{token} | public, signed | file bytes (local storage backend only; S3 uses presigned URLs) |

Exports apply every change not explicitly rejected. `ats_report` and `feedback_report` are DOCX summaries. `pdf` keeps the original layout for text-PDF sources when the edits fit, otherwise converts the DOCX and returns `503 pdf_unavailable` when LibreOffice is missing. Generated versions expose `render: {mode: docx_in_place|pdf_in_place|template, fallback_reason}`.

## Applications
CRUD at `/applications` (GET list, POST) and `/applications/{id}` (GET, PATCH, DELETE 204) with `{company, role_title, status, applied_at?, reminder_at?, notes?, job_posting_id?, resume_version_id?}`.

## Billing
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /billing/status | | `{free_used, free_limit, subscription: {id, stripe_subscription_id, status, current_period_end, cancel_at_period_end}|null, pay_per_use_credits}` (`subscription` is the active one, else the latest) |
| POST | /billing/checkout | `{mode: subscription|pay_per_use}` | `{checkout_url}` (owner/admin only) |
| POST | /billing/portal | | `{portal_url}` Stripe customer portal (owner/admin only). 409 `no_billing_account` if the org has never started checkout |
| POST | /billing/webhook | Stripe event (signature verified) | 200 `{status}` where status is `processed`, `duplicate` or `ignored`; 400 `invalid_signature`; 413 body over 1 MB |

`POST /billing/checkout` also returns 409 `already_subscribed` when `mode=subscription` and the organization already has an active, trialing or past-due subscription (use the portal instead), and 503 `billing_unavailable` when Stripe is not configured.

## Ops
Served at the root, not under `/v1`: `GET /healthz` (liveness), `GET /readyz` (DB and Redis), `GET /metrics` (Prometheus).
