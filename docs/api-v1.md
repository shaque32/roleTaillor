# RoleTailor API v1 (contract)

All routes are under `/v1`, JSON unless noted, and documented live at `/docs` (OpenAPI).
Auth is an opaque bearer session token (`Authorization: Bearer <token>`), stored hashed in
`sessions`. Every request carries or receives an `X-Correlation-ID`. Errors use
`{"error": {"code": "...", "message": "...", "details": {...}}}`.

## Auth and profile
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /auth/register | `{email, password, full_name}` | `{token, user, organization}` |
| POST | /auth/login | `{email, password, device_label?}` | `{token, user, organization}` |
| POST | /auth/logout | | 204 |
| GET | /me | | `user` (profile + preferences) |
| PATCH | /me | any of `full_name, address, contact_number, linkedin_url, preferred_page_limit, industry_focus, resume_tone, ats_preference, technical_depth, preferred_template_id` | `user` |
| DELETE | /me | | 202 (right to delete) |
| GET | /me/export | | JSON data export |
| POST | /consents | `{purpose: "ai_processing", policy_version, granted}` | consent row |

AI routes return `428 consent_required` until the user grants `ai_processing` consent.

## Resumes
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /resumes | | `[{id, name, origin, created_at, latest_version}]` |
| POST | /resumes | multipart `file` (DOCX/PDF), `name` | `{resume, version}` where version has `blocks`, `findings`, `layout_metadata` |
| POST | /resumes/guided | `{name, contact, sections:[{kind, title, items:[...]}]}` | `{resume, version}` |
| GET | /resumes/{id} | | resume with `versions[]` |
| PATCH | /resumes/{id} | `{name}` | resume |
| DELETE | /resumes/{id} | | 204 (archives) |
| GET | /resumes/{id}/versions/{vid} | | version |
| POST | /resumes/{id}/versions/{vid}/restore | | new version copied from `vid` |

## Jobs
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /jobs | `{source_url?, description?, title?, company?}` | job posting. URL fetch failure returns `422 job_url_unreadable` so the UI asks for a paste |

## Tailoring workflows
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /workflows | `{resume_version_id, job_posting_id, page_limit?, accept_paid_usage?}` + `Idempotency-Key` header | `202 workflow`. `402 payment_required` with `{options}` when free quota is used up and no subscription; resend with `accept_paid_usage: true` after checkout |
| GET | /workflows | | dashboard rows `{id, status, resume_name, target_role, company, ats_score, simulation_score, created_at}` |
| GET | /workflows/{id} | | `{workflow, latest: generated_resume, scores_before, gaps, feedback, changes[]}` |
| POST | /workflows/{id}/iterations | `{focus_block_ids?, instructions?}` | `202`. Same role, no credit consumed |
| POST | /workflows/{id}/pause, /resume, /cancel | | workflow |

Workflow `status`: draft, queued, running, paused, completed, failed, cancelled. Poll `GET /workflows/{id}` every 2 seconds while queued or running.

## Review and export
| Method | Path | Body | Returns |
|---|---|---|---|
| PATCH | /generated/{gid}/changes/{cid} | `{decision: accepted|rejected|pending}` | change |
| POST | /generated/{gid}/approve | | generated resume |
| POST | /generated/{gid}/exports | `{kind: docx|pdf|ats_report|feedback_report}` | `{export_id, download_url, expires_at}` |
| POST | /exports/{eid}/share | `{expires_in_hours}` | `{url}` |

Exports apply every change not explicitly rejected.

## Applications
CRUD at `/applications` with `{company, role_title, status, applied_at?, reminder_at?, notes?, job_posting_id?, resume_version_id?}`.

## Billing
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /billing/status | | `{free_used, free_limit, subscription: {...}|null, pay_per_use_credits}` |
| POST | /billing/checkout | `{mode: subscription|pay_per_use}` | `{checkout_url}` |
| POST | /billing/webhook | Stripe event (signature verified) | 200 |

## Ops
`GET /healthz` (liveness), `GET /readyz` (DB and Redis), `GET /metrics` (Prometheus).
