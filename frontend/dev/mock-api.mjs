// Dependency-free mock of the RoleTailor FastAPI backend (everything under /v1 used by lib/api.ts).
// Run: node dev/mock-api.mjs   (PORT=8787 by default; MOCK_NEW_USER=1 simulates a fresh account)
import http from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.PORT || 8787);
const NEW_USER = process.env.MOCK_NEW_USER === "1";
const UNVERIFIED = process.env.MOCK_UNVERIFIED === "1"; // user starts with an unconfirmed email
const ORIGIN = `http://localhost:${PORT}`;
const ago = (days, hours = 0) => new Date(Date.now() - days * 864e5 - hours * 36e5).toISOString();
const ahead = (days) => new Date(Date.now() + days * 864e5).toISOString();
const uid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

/* ---------------- fixtures ---------------- */
const user = {
  id: uid(1),
  email: "jordan.lee@example.com",
  email_verified_at: UNVERIFIED ? null : ago(119),
  full_name: "Jordan Lee",
  address: { line1: "214 Alder Street", city: "Portland", region: "OR", postal_code: "97205", country: "US" },
  contact_number: "+1 503 555 0142",
  linkedin_url: "https://www.linkedin.com/in/jordan-lee-demo",
  preferred_page_limit: 2,
  industry_focus: "Data platforms and analytics",
  resume_tone: "professional",
  ats_preference: "balanced",
  technical_depth: "high",
  preferred_template_id: null,
  created_at: ago(120),
};
const organization = { id: uid(2), name: "Jordan Lee (Personal)", free_generation_limit: 10 };
let consentGranted = !NEW_USER;
const consents = [];

const B = (id, text, o = {}) => ({ id, kind: "paragraph", text, style_name: o.h ? "Heading 1" : o.li ? "List Bullet" : "Normal", is_list_item: !!o.li, is_heading: !!o.h, editable: o.editable !== false });
const blocksV1 = [
  B("b1", "Jordan Lee"),
  B("b2", "Senior Data Engineer · Portland, OR · jordan.lee@example.com · +1 503 555 0142", { editable: false }),
  B("b3", "Summary", { h: 1 }),
  B("b4", "Data engineer with 8 years of experience building batch and streaming pipelines for analytics teams. Comfortable owning a platform end to end."),
  B("b5", "Experience", { h: 1 }),
  B("b6", "Senior Data Engineer, Fernhill Analytics (2021 - Present)"),
  B("b7", "Built ETL pipelines in Python and Airflow that load 2 TB of data per day into the warehouse.", { li: 1 }),
  B("b8", "Worked with analysts to make dashboards faster and cheaper to run.", { li: 1 }),
  B("b9", "Led a small team of three engineers migrating legacy jobs to dbt.", { li: 1 }),
  B("b10", "Data Engineer, Northwind Logistics (2017 - 2021)"),
  B("b11", "Wrote SQL and Spark jobs for shipment tracking reports.", { li: 1 }),
  B("b12", "Set up monitoring for failed jobs and cut on-call pages by a third.", { li: 1 }),
  B("b13", "Education", { h: 1 }),
  B("b14", "B.S. Computer Science, Oregon State University (2013 - 2017)"),
  B("b15", "Skills", { h: 1 }),
  B("b16", "Python, SQL, Spark, Airflow, dbt, Snowflake, AWS, Kafka, Terraform"),
];
const blocksV2 = blocksV1.map((b) => (b.id === "b8" ? { ...b, text: "Partnered with analysts to cut dashboard query cost by 40 percent." } : b));
const findings = [
  { code: "table_layout_detected", detail: "Contact details sit in a table; they were read but kept exactly as written.", severity: "info", block_id: "b2" },
  { code: "date_format_inconsistent", detail: "Some dates use a hyphen and others an en dash. Both were read correctly.", severity: "warn", block_id: "b10" },
];

const resumes = NEW_USER ? [] : [
  { id: uid(10), name: "Jordan Lee - Data Engineering", origin: "upload", created_at: ago(60), archived_at: null,
    versions: [{ id: uid(11), version_number: 1, created_at: ago(60) }, { id: uid(12), version_number: 2, created_at: ago(14) }] },
  { id: uid(20), name: "Jordan Lee - Analytics Lead", origin: "guided", created_at: ago(9), archived_at: null,
    versions: [{ id: uid(21), version_number: 1, created_at: ago(9) }] },
];
const versionData = {
  [uid(11)]: { blocks: blocksV1, parent: null, resume: uid(10) },
  [uid(12)]: { blocks: blocksV2, parent: uid(11), resume: uid(10) },
  [uid(21)]: { blocks: blocksV2.map((b) => ({ ...b, id: "g" + b.id.slice(1) })), parent: null, resume: uid(20) },
};
const resumeListItem = (r) => ({ id: r.id, name: r.name, origin: r.origin, created_at: r.created_at, latest_version: [...r.versions].sort((a, b) => b.version_number - a.version_number)[0] ?? null });
const resumeVersion = (vid) => {
  const d = versionData[vid];
  if (!d) return null;
  const r = resumes.find((x) => x.id === d.resume);
  const s = r.versions.find((v) => v.id === vid);
  return { id: vid, version_number: s.version_number, created_at: s.created_at, resume_id: d.resume, parent_version_id: d.parent, blocks: d.blocks, findings: vid === uid(21) ? [] : findings, layout_metadata: { pages: 2, font: "Calibri", margins_in: 0.8 } };
};

const jobs = {
  [uid(30)]: { id: uid(30), source_url: "https://careers.lumenbank.example/jobs/4471", title: "Staff Data Engineer", company: "Lumen Bank", description: "Own our streaming and batch data platform. Kafka, Spark, Snowflake, dbt, data quality, mentoring.", created_at: ago(3) },
  [uid(31)]: { id: uid(31), source_url: null, title: "Analytics Engineering Lead", company: "Tidewater Health", description: "Lead analytics engineering; dbt, Looker, stakeholder management.", created_at: ago(2) },
  [uid(32)]: { id: uid(32), source_url: null, title: "Senior Data Platform Engineer", company: "Orchard Cloud", description: "Terraform, Kubernetes, Kafka, Python.", created_at: ago(1) },
  [uid(33)]: { id: uid(33), source_url: null, title: "Data Engineer", company: "Pinecone Retail", description: "SQL, Airflow, Spark.", created_at: ago(8) },
};

const wf = (n, status, job, v, extra = {}) => ({
  id: uid(n), status, page_limit: 2, source_resume_version_id: v, job_posting_id: job,
  created_at: extra.created_at, updated_at: extra.updated_at ?? extra.created_at, stage: null, recovery_message: null, error: null,
  resume_name: extra.resume_name, target_role: jobs[job].title, company: jobs[job].company,
});
const DE = "Jordan Lee - Data Engineering", AL = "Jordan Lee - Analytics Lead";
const workflows = NEW_USER ? [] : [
  wf(100, "completed", uid(30), uid(12), { created_at: ago(3), resume_name: DE }),
  wf(101, "running", uid(32), uid(12), { created_at: ago(0, 0.1), resume_name: DE, updated_at: ago(0) }),
  wf(102, "completed", uid(31), uid(21), { created_at: ago(2), resume_name: AL }),
  wf(103, "failed", uid(33), uid(11), { created_at: ago(8), resume_name: DE }),
];
if (!NEW_USER) workflows[1].stage = "plan";
if (!NEW_USER) workflows[3].recovery_message = "The job page could not be matched to your resume. Nothing was charged. Try again or paste the job description.";
const feedback = {
  overall: 82, technical_alignment: 88, leadership: 74, domain_alignment: 69, communication: 85, interview_likelihood: "high",
  strengths: ["Clear ownership of a production data platform", "Quantified pipeline scale (2 TB per day)", "Strong dbt and Airflow match to the posting"],
  weaknesses: ["No direct banking or regulated-data experience", "Streaming work is mentioned but not quantified"],
  suggested_improvements: ["Add a metric to the Kafka work", "Mention data quality testing practices explicitly"],
  competitive_positioning: "Stronger on platform ownership than the typical applicant pool; thinner on domain background.",
};
const gen = (n, wfId, vid, scores, extra = {}) => ({
  id: uid(n), workflow_id: uid(wfId), iteration: extra.iteration ?? 2, resume_version_id: vid,
  ats_score: scores[0], job_alignment_score: scores[1], keyword_relevance_score: scores[2], formatting_score: scores[3], simulation_score: 82,
  simulated_feedback: feedback, approved_at: extra.approved_at ?? null, created_at: ago(3),
});
const generated = [gen(200, 100, uid(12), [91, 86, 89, 94]), gen(201, 102, uid(21), [87, 90, 84, 92], { iteration: 1, approved_at: ago(2) })];
const CH = (n, gid, path, prior, proposed, reason, kw, decision) => ({
  id: uid(n), generated_resume_id: uid(gid), block_path: path, prior_text: prior, proposed_text: proposed, reason, prioritized_keywords: kw,
  decision, decided_at: decision === "pending" ? null : ago(3, 2),
});
const changes = [
  CH(300, 200, "b4", blocksV2[3].text, "Senior data engineer with 8 years of experience building batch and streaming pipelines for analytics teams, owning platforms end to end from ingestion to governed warehouse models.", "Mirrors the posting's emphasis on platform ownership and governed data.", ["streaming", "platform ownership"], "accepted"),
  CH(301, 200, "b7", blocksV2[6].text, "Built and operated Python and Airflow ETL pipelines loading 2 TB of data per day into Snowflake, with automated data quality checks.", "The job asks for Snowflake and data quality; both appear elsewhere in your resume.", ["Snowflake", "data quality", "Airflow"], "accepted"),
  CH(302, 200, "b8", blocksV2[7].text, "Partnered with analysts to cut dashboard query cost by 40 percent through warehouse model and clustering changes.", "Moves your existing metric closer to the platform-cost language in the job.", ["cost optimization"], "pending"),
  CH(303, 200, "b9", blocksV2[8].text, "Led a team of three engineers migrating legacy jobs to dbt, mentoring on testing and code review practices.", "The posting lists mentoring as a core responsibility.", ["dbt", "mentoring"], "rejected"),
  CH(304, 200, "b12", blocksV2[11].text, "Implemented job monitoring and alerting that cut on-call pages by a third.", "Tighter phrasing; same fact.", ["monitoring"], "pending"),
  CH(305, 200, "b16", blocksV2[15].text, "Kafka, Spark, Snowflake, dbt, Airflow, Python, SQL, Terraform, AWS", "Reorders skills to lead with the job's top requirements.", ["Kafka", "Spark", "Snowflake"], "accepted"),
];
const changes2 = [
  CH(310, 201, "g4", "Data engineer with 8 years of experience building batch and streaming pipelines for analytics teams. Comfortable owning a platform end to end.", "Analytics-minded data engineer with 8 years of experience, translating pipelines into trusted metrics for stakeholders.", "Leans into the stakeholder language in the posting.", ["stakeholder management"], "accepted"),
  CH(311, 201, "g9", "Led a small team of three engineers migrating legacy jobs to dbt.", "Led three engineers migrating legacy jobs to dbt, defining the team's modeling standards.", "Highlights lead-level scope.", ["dbt", "leadership"], "accepted"),
];
const scoresBefore = { ats: 64, job_alignment: 58, keyword_relevance: 49, formatting: 90 };
const gaps = ["Kubernetes", "Data governance", "Banking or financial services domain", "Looker"];

const applications = NEW_USER ? [] : [
  { id: uid(400), company: "Lumen Bank", role_title: "Staff Data Engineer", status: "applied", applied_at: ago(2), reminder_at: ahead(5), notes: "Referred by a former colleague. Follow up Friday.", job_posting_id: uid(30), resume_version_id: uid(12), created_at: ago(3) },
  { id: uid(401), company: "Tidewater Health", role_title: "Analytics Engineering Lead", status: "interviewing", applied_at: ago(12), reminder_at: ahead(1), notes: "Panel interview with the data team on Thursday.", job_posting_id: uid(31), resume_version_id: uid(21), created_at: ago(14) },
  { id: uid(402), company: "Orchard Cloud", role_title: "Senior Data Platform Engineer", status: "saved", applied_at: null, reminder_at: null, notes: null, job_posting_id: uid(32), resume_version_id: null, created_at: ago(1) },
  { id: uid(403), company: "Pinecone Retail", role_title: "Data Engineer", status: "rejected", applied_at: ago(30), reminder_at: null, notes: "Position filled internally.", job_posting_id: null, resume_version_id: uid(11), created_at: ago(32) },
  { id: uid(404), company: "Harbor Mutual", role_title: "Principal Data Engineer", status: "offered", applied_at: ago(40), reminder_at: ahead(3), notes: "Offer received; decision due next week.", job_posting_id: null, resume_version_id: uid(12), created_at: ago(44) },
];
const billing = { free_used: NEW_USER ? 0 : 3, free_limit: 10, subscription: null, pay_per_use_credits: NEW_USER ? 0 : 2 };
const exportsMap = {};

/* ---------------- helpers ---------------- */
const rowOf = (w) => {
  const g = generated.find((x) => x.workflow_id === w.id);
  return { id: w.id, status: w.status, resume_name: w.resume_name, target_role: w.target_role, company: w.company, ats_score: g?.ats_score ?? null, simulation_score: g?.simulation_score ?? null, created_at: w.created_at };
};
const detailOf = (w) => {
  const g = [...generated].reverse().find((x) => x.workflow_id === w.id) ?? null;
  const done = Boolean(g);
  return { workflow: w, latest: g, scores_before: done ? scoresBefore : null, gaps: done ? gaps : [], feedback: done ? feedback : null, changes: done ? [...changes, ...changes2].filter((c) => c.generated_resume_id === g.id) : [] };
};
// Running workflow advances to a "stage" over time so the progress screen is alive but stays running for screenshots.
const readBody = (req) => new Promise((res) => { const c = []; req.on("data", (d) => c.push(d)); req.on("end", () => res(Buffer.concat(c))); req.on("error", () => res(Buffer.alloc(0))); });
const send = (res, status, body, headers = {}) => {
  if (status === 204 || body === undefined) { res.writeHead(status, headers); return res.end(); }
  res.writeHead(status, { "Content-Type": "application/json", ...headers });
  res.end(JSON.stringify(body));
};
const err = (res, status, code, message) => send(res, status, { error: { code, message, details: {} } });

const PDF = Buffer.from("%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n");

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, ORIGIN);
  const p = url.pathname.replace(/\/+$/, "");
  const m = req.method;
  const raw = await readBody(req);
  const ctype = req.headers["content-type"] || "";
  let body = {};
  if (ctype.includes("application/json") && raw.length) { try { body = JSON.parse(raw.toString()); } catch { return err(res, 400, "invalid_body", "Bad JSON."); } }
  console.log(m, p);

  if (p === "/v1/files/demo.pdf") return (res.writeHead(200, { "Content-Type": "application/pdf" }), res.end(PDF));
  if (!p.startsWith("/v1/")) return err(res, 404, "not_found", "Not found.");
  const parts = p.slice(4).split("/").filter(Boolean).map(decodeURIComponent);
  const [a, b, c, d, e] = parts;

  // auth
  if (a === "auth") {
    if (b === "forgot-password") return send(res, 202, { status: "accepted" });
    if (b === "reset-password") {
      if (!body.token || body.token === "bad") return err(res, 400, "invalid_token", "This link is invalid or has expired.");
      if (String(body.password || "").length < 10) return err(res, 422, "weak_password", "Use at least 10 characters.");
      return send(res, 200, { status: "password_reset" });
    }
    if (b === "verify-email" && !c) {
      if (!body.token || body.token === "bad") return err(res, 400, "invalid_token", "This link is invalid or has expired.");
      user.email_verified_at = new Date().toISOString();
      return send(res, 200, { status: "verified" });
    }
    if (b === "verify-email" && c === "resend") {
      if (!/^Bearer \S+/.test(req.headers.authorization || "")) return err(res, 401, "unauthenticated", "Please sign in.");
      if (user.email_verified_at) return send(res, 200, { status: "already_verified" });
      return send(res, 202, { status: "sent" });
    }
    if (b === "logout") return send(res, 204);
    if (b === "login" || b === "register") {
      if (b === "register" || body.email) {
        if (b === "register") {
          if (body.email) user.email = body.email;
          if (body.full_name) user.full_name = body.full_name;
        }
        return send(res, b === "register" ? 201 : 200, { token: "demo-token-" + randomUUID(), expires_at: ahead(14), user, organization });
      }
      return err(res, 401, "invalid_credentials", "Bad credentials.");
    }
  }
  if (!/^Bearer \S+/.test(req.headers.authorization || "")) return err(res, 401, "unauthenticated", "Please sign in.");

  if (a === "me") {
    if (parts.length === 1) {
      if (m === "GET") return send(res, 200, user);
      if (m === "PATCH") return send(res, 200, Object.assign(user, body));
      if (m === "DELETE") return send(res, 204);
    }
    if (b === "export") return send(res, 200, { user, resumes, applications });
  }
  if (a === "consents" && m === "POST") {
    consentGranted = Boolean(body.granted);
    const rec = { id: randomUUID(), purpose: body.purpose, policy_version: body.policy_version, granted: consentGranted, recorded_at: new Date().toISOString() };
    consents.push(rec);
    return send(res, 201, rec);
  }
  if (a === "consents" && m === "GET") return send(res, 200, consents);

  // resumes
  if (a === "resumes") {
    if (parts.length === 1) {
      if (m === "GET") return send(res, 200, resumes.filter((r) => !r.archived_at).map(resumeListItem));
      if (m === "POST") {
        const name = ctype.includes("multipart") ? (/name="name"\r\n\r\n([^\r]*)/.exec(raw.toString("latin1"))?.[1] || "Uploaded resume") : "Uploaded resume";
        return send(res, 201, newResume(name, "upload", blocksV1));
      }
    }
    if (b === "text" && m === "POST") return send(res, 201, newResume(body.name || "Pasted resume", "upload", blocksV1));
    if (b === "guided" && m === "POST") {
      const bl = [B("b1", body.contact?.full_name || "Jordan Lee"), ...(body.sections || []).flatMap((s, i) => [B(`s${i}`, s.title, { h: 1 }), ...s.items.map((it, j) => B(`s${i}i${j}`, it.company || it.institution || it.name || it.text || "Item"))])];
      return send(res, 201, newResume(body.name || "New resume", "guided", bl));
    }
    const r = resumes.find((x) => x.id === b);
    if (!r) return err(res, 404, "not_found", "Resume not found.");
    if (parts.length === 2) {
      if (m === "GET") return send(res, 200, r);
      if (m === "PATCH") { r.name = body.name ?? r.name; return send(res, 200, r); }
      if (m === "DELETE") { r.archived_at = new Date().toISOString(); return send(res, 204); }
    }
    if (c === "versions" && d) {
      if (parts.length === 4 && m === "GET") { const v = resumeVersion(d); return v ? send(res, 200, v) : err(res, 404, "not_found", "Version not found."); }
      if (e === "restore" && m === "POST") {
        const src = versionData[d];
        if (!src) return err(res, 404, "not_found", "Version not found.");
        const id = randomUUID(); const n = Math.max(...r.versions.map((v) => v.version_number)) + 1;
        r.versions.push({ id, version_number: n, created_at: new Date().toISOString() });
        versionData[id] = { blocks: src.blocks, parent: d, resume: r.id };
        return send(res, 201, resumeVersion(id));
      }
    }
  }
  function newResume(name, origin, blocks) {
    const rid = randomUUID(), vid = randomUUID(), now = new Date().toISOString();
    const r = { id: rid, name, origin, created_at: now, archived_at: null, versions: [{ id: vid, version_number: 1, created_at: now }] };
    resumes.push(r);
    versionData[vid] = { blocks, parent: null, resume: rid };
    return { resume: resumeListItem(r), version: resumeVersion(vid) };
  }

  // jobs
  if (a === "jobs" && m === "POST") {
    if (body.source_url && /unreadable|blocked/.test(body.source_url)) return err(res, 422, "job_url_unreadable", "Could not read that page.");
    const j = { id: randomUUID(), source_url: body.source_url ?? null, title: body.title ?? "Untitled role", company: body.company ?? "Unknown company", description: body.description ?? null, created_at: new Date().toISOString() };
    jobs[j.id] = j;
    return send(res, 201, j);
  }

  // workflows
  if (a === "workflows") {
    if (parts.length === 1) {
      if (m === "GET") return send(res, 200, workflows.map(rowOf));
      if (m === "POST") {
        if (!user.email_verified_at) return err(res, 403, "email_unverified", "Confirm your email first.");
        if (!consentGranted) return err(res, 428, "consent_required", "AI processing consent required.");
        const j = jobs[body.job_posting_id];
        const vid = body.resume_version_id;
        const rn = resumes.find((r) => r.id === versionData[vid]?.resume)?.name ?? "Resume";
        const w = { id: randomUUID(), status: "queued", page_limit: body.page_limit ?? 2, source_resume_version_id: vid, job_posting_id: body.job_posting_id, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), stage: null, recovery_message: null, error: null, resume_name: rn, target_role: j?.title ?? null, company: j?.company ?? null };
        workflows.push(w);
        return send(res, 201, w);
      }
    }
    const w = workflows.find((x) => x.id === b);
    if (!w) return err(res, 404, "not_found", "Workflow not found.");
    if (parts.length === 2 && m === "GET") return send(res, 200, detailOf(w));
    if ((c === "iterations" || c === "resume") && m === "POST" && !user.email_verified_at) return err(res, 403, "email_unverified", "Confirm your email first.");
    if (c === "iterations" && m === "POST") { w.status = "queued"; return send(res, 202, w); }
    if (c === "pause") { w.status = "paused"; return send(res, 200, w); }
    if (c === "resume") { w.status = "running"; return send(res, 200, w); }
    if (c === "cancel") { w.status = "cancelled"; return send(res, 200, w); }
  }

  // generated
  if (a === "generated") {
    const g = generated.find((x) => x.id === b);
    if (!g) return err(res, 404, "not_found", "Generated resume not found.");
    if (c === "changes" && d && m === "PATCH") {
      const ch = [...changes, ...changes2].find((x) => x.id === d);
      if (!ch) return err(res, 404, "not_found", "Change not found.");
      ch.decision = body.decision; ch.decided_at = body.decision === "pending" ? null : new Date().toISOString();
      return send(res, 200, ch);
    }
    if (c === "approve" && m === "POST") { g.approved_at = new Date().toISOString(); return send(res, 200, g); }
    if (c === "exports" && m === "POST") {
      const id = randomUUID(); exportsMap[id] = body.kind;
      return send(res, 201, { export_id: id, download_url: `${ORIGIN}/v1/files/demo.pdf`, expires_at: ahead(1) });
    }
  }
  if (a === "exports" && c === "share" && m === "POST") return send(res, 201, { url: `${ORIGIN}/v1/files/demo.pdf?share=${b}` });

  // applications
  if (a === "applications") {
    if (parts.length === 1) {
      if (m === "GET") return send(res, 200, applications);
      if (m === "POST") { const x = { id: randomUUID(), created_at: new Date().toISOString(), ...body }; applications.push(x); return send(res, 201, x); }
    }
    const x = applications.find((y) => y.id === b);
    if (!x) return err(res, 404, "not_found", "Application not found.");
    if (m === "PATCH") return send(res, 200, Object.assign(x, body));
    if (m === "DELETE") { applications.splice(applications.indexOf(x), 1); return send(res, 204); }
  }

  // billing
  if (a === "billing") {
    if (b === "status") return send(res, 200, billing);
    if (b === "portal") return send(res, 200, { portal_url: `${ORIGIN}/v1/files/demo.pdf` });
    if (b === "checkout") return send(res, 200, { checkout_url: `${ORIGIN}/v1/files/demo.pdf` });
  }
  return err(res, 404, "not_found", `No mock for ${m} ${p}`);
});

const HOST = process.env.HOST || "127.0.0.1";
server.listen(PORT, HOST, () => console.log(`RoleTailor mock API on ${ORIGIN}/v1 (new user: ${NEW_USER})`));
