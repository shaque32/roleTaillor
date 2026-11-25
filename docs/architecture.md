# RoleTailor architecture

## Principles
1. **Models fill typed slots; code orchestrates.** No agent framework and no free-running agent loop at serving time. Each AI step is one call with a versioned prompt and a pydantic output schema.
2. **The AI never regenerates the document.** DOCX files are parsed into blocks (semantic text nodes). Models return replacement text by block id. The documents engine applies it at the XML run level, so styles, spacing, tabs, numbering, and section order are untouched.
3. **Truth is enforced by code, not by asking nicely.** Every rewrite passes deterministic gates and a claim check, or the original text is kept. A generation degrades to fewer changes, never to invented ones.
4. **Cheapest model that holds quality, per stage.** Routing, failover, escalation, and prices live in `config/models.yaml`. Changing a model is a config change, measured by the eval harness.

## Request flow
```
Next.js ──► FastAPI (/v1, RLS tenant tx) ──► Celery task (Redis)
                                                 │
   ┌─────────────────────────────────────────────┴────────────────────────────┐
   │ 1 structure_resume  low   cached per resume version (resume_versions.content)
   │ 2 analyze_job       low   cached per JD hash (job_postings.structured_requirements)
   │ 3 plan              mid   evidence-matched keyword plan, escalates if confidence < 0.6
   │ 4 rewrite           low   parallel batches, length budget per block
   │ 5 validate          code  numbers, terms, keywords, length, phrasing, stuffing
   │   verify_claims     low   entailment check of each rewrite against its original
   │   retry → escalate → revert to original
   │ 6 page limit        code  render via LibreOffice, revert growing edits until it fits
   │ 7 score             code  ATS / alignment / keyword / formatting, before and after
   │ 8 feedback          low   simulated hiring-manager review (labelled as simulation)
   └─────────────────────────────────────────────┬────────────────────────────┘
                                                 ▼
          resume_versions (child), generated_resumes, resume_changes,
          validation_results, ai_metrics, usage_tracking (charge on success only)
```

## How the mega prompt maps to the system
| Mega-prompt agent | Implementation | Model tier |
|---|---|---|
| Resume Analysis Agent | `structure_resume` stage + deterministic parser | low, cached |
| Job Analysis Agent | `analyze_job` stage | low, cached |
| Resume Tailoring Agent | `plan` + `rewrite` stages | mid + low |
| Validation Agent | deterministic gates + `verify_claims` | code + low |
| Formatting Preservation Agent | documents engine (XML-level edits, page check) | no model |
| Resume Scoring Agent | deterministic scoring + `feedback` stage | code + low |

"Multi-agent coordination" is the orchestrator: plain Python with explicit retries and fallbacks, which keeps cost and behaviour predictable and auditable.

## Model routing (`config/models.yaml`)
- Tiers: low = Claude Haiku 5.5 then DeepSeek chat; medium = Claude Sonnet 5.5 then DeepSeek reasoner; high = Claude Opus 5.5.
- Failover within a tier on provider errors, with a per-model circuit breaker.
- Schema-invalid output is retried once with the validation error, then fails over.
- Escalation one tier at a time, capped per stage (`max_tier`): on low plan confidence and on the third rewrite round.
- Enterprise customers start `plan` and `rewrite` one tier higher.
- Every attempt is one `ai_metrics` row: model, prompt version, tier, routing reason, tokens, cost, latency, status.

## Cost per generation (estimate, verify with `evals/run_evals.py --live`)
| Stage | Model | Approx. tokens in / out | Cost |
|---|---|---|---|
| structure_resume (once per resume) | Haiku 5.5 | 3.5k / 3k | $0.002 |
| analyze_job (once per JD) | Haiku 5.5 | 2k / 1.2k | $0.001 |
| plan | Sonnet 5.5, effort low | 6k / 2.5k | $0.037 |
| rewrite (2 batches) | Haiku 5.5 | 5k / 3k | $0.002 |
| verify_claims | Haiku 5.5 | 3k / 0.8k | $0.001 |
| feedback | Haiku 5.5 | 3.5k / 0.8k | $0.001 |
| **Total** | | | **about $0.04** (about $0.01 with plan on Haiku) |

Against $0.50 pay-per-use, AI cost is under 10% of revenue per generation. Iterations on the same job skip stages 1 and 2 and only rewrite the focused blocks. Cost levers already in place: stage caching in Postgres, an exact-match response cache in Redis, static system prompts first (provider prompt caching), compact JSON payloads, and parallel cheap rewrites. The single biggest lever left is moving `plan` to the low tier; run the live eval with `--stage-tier plan=low` and switch if fabrication stays at zero and coverage holds.

## Prompts
`backend/roletailor/ai/prompts/<stage>.v<N>.md`, front matter plus a static system prompt that includes the shared `_partials/guardrails.md`. Per-request data goes only in the user message as JSON, so every version is a stable cache prefix. Versions are synced into `prompt_versions` on first use and pinned per environment in `prompt_pins` (rollback is a pin change).

## Validation gates (`pipeline/validation/rules.py`)
| Rule | Blocks when the rewrite |
|---|---|
| facts.numbers | contains any number not in the original line |
| facts.terms | names a tool, product, or proper noun not in the original line (summary and skills lines may also use the fact inventory) |
| facts.keywords | contains a job keyword the original does not support |
| facts.claims | fails the model claim check (inflated scope, new responsibilities) |
| layout.length | moves outside ±15% of the original length |
| authenticity.phrases | adds generic or AI-sounding phrasing |
| authenticity.stuffing | repeats a keyword or adds more than three |
| layout.page_limit | pushes the rendered document past the page limit |
Document-level warnings cover keyword density and repeated opening verbs. All outcomes land in `validation_results`.

## Tenancy and security
The schema's RLS is kept as designed: the app connects as a non-BYPASSRLS role and sets `app.organization_id` per transaction. Global tables (users, sessions, catalog, prompts, models) are accessed outside tenant context. Sessions are opaque tokens stored hashed. AI processing requires recorded consent. Uploads are type-checked, size-limited, hashed, and scan-gated.

## MVP vs later
| MVP (this slice) | Phase 2 | Enterprise |
|---|---|---|
| DOCX and text-PDF in-place tailoring, OCR for scanned PDFs (template output), guided builder | Reflow that moves later lines when an edit needs an extra line, embeddings for semantic match (pgvector), semantic cache | SSO/SAML, tenant AI policies and prompt packs |
| Staged pipeline, gates, evals, cost telemetry | Batch API for non-urgent re-scoring, A/B of prompt versions | Private model deployments, CMEK |
| Auth, RLS, billing, exports, share links | Cover letters, interview prep | ATS/CRM/HRIS integrations, audit exports |

## PDF sources

Text PDFs are edited in place (`documents/pdf_layout.py`, `pdf_writer.py`): the reader groups
glyphs into lines and blocks with their geometry and fonts; the writer removes the old text
operators from the content stream (no white boxes, so ATS parsers never see stale text) and
draws the new text at the same position in the stream, on the same baselines, in the original
font. When the embedded font subset lacks a glyph, a metric-compatible open font is embedded
(Carlito for Calibri, Caladea for Cambria, Liberation for Arial/Times/Courier). Every output is
re-read and compared with the intended text before it is accepted.

An edit that cannot keep the layout (needs more lines than it had even at 90% size, spans two
columns of a line, changes a bold label, sits in a form XObject) is handled in the pipeline
step `layout.pdf_in_place`: a minority of such edits is reverted so the layout holds; if more
than half would be lost, all edits are kept and the result is rendered through the ATS
template. Generated versions record `content.render = {mode, fallback_reason}`.

Scanned PDFs (no text layer) are read with Tesseract through `documents/ocr.py` (about 2 s per
page, at most 6 pages). They carry the findings `ocr_applied` and, under 70% confidence,
`ocr_low_confidence`, and are always rendered through the template.

Licensing: the PDF stack is pdfplumber/pdfminer.six (MIT), pikepdf (MPL-2.0), fontTools (MIT),
reportlab (BSD), pypdfium2 (Apache-2.0/BSD) and Tesseract (Apache-2.0). PyMuPDF and Ghostscript
(both AGPL) are deliberately not used.
