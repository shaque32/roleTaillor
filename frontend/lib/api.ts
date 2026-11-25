import type {
  Application,
  ApplicationBody,
  AuthResponse,
  BillingStatus,
  CheckoutMode,
  CheckoutResult,
  PortalResult,
  Consent,
  ConsentBody,
  ExportKind,
  ExportResult,
  GeneratedResume,
  GuidedResumeBody,
  IterationBody,
  JobBody,
  JobPosting,
  LoginBody,
  RegisterBody,
  ResumeChange,
  ChangeDecision,
  ResumeDetail,
  ResumeListItem,
  ResumeVersion,
  ResumeWithVersion,
  ShareResult,
  User,
  UserPatch,
  Workflow,
  WorkflowCreateBody,
  WorkflowDetail,
  WorkflowRow,
} from "./types";

/** Policy version recorded with the AI processing consent. */
export const AI_POLICY_VERSION = "2026-11";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FRIENDLY: Record<number, string> = {
  401: "Your session has ended. Please sign in again.",
  403: "You don't have access to that.",
  404: "We couldn't find that.",
  429: "You're going a little fast. Please wait a moment and try again.",
  500: "Something went wrong on our side. Please try again.",
  502: "We couldn't reach RoleTailor. Please try again shortly.",
  503: "RoleTailor is temporarily unavailable. Please try again shortly.",
};

export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = FRIENDLY[res.status] ?? "Something went wrong. Please try again.";
  let details: Record<string, unknown> = {};
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string; details?: Record<string, unknown> }; detail?: unknown };
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message || message;
      details = body.error.details ?? {};
    } else if (typeof body?.detail === "string") {
      message = body.detail;
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, code, message, details);
}

type Json = Record<string, unknown> | unknown[];
interface RequestOpts {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  json?: Json | object;
  form?: FormData;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function handleUnauthenticated() {
  if (typeof window === "undefined") return;
  const here = window.location.pathname + window.location.search;
  if (!here.startsWith("/login")) window.location.assign(`/login?next=${encodeURIComponent(here)}`);
}

export async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  let res: Response;
  try {
    res = await fetch(`/api/proxy${path}`, {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "You appear to be offline. Check your connection and try again.");
  }
  if (!res.ok) {
    const err = await toApiError(res);
    if (res.status === 401) handleUnauthenticated();
    throw err;
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/* ---------- Session (via app/api/session) ---------- */
async function session<T>(method: "POST" | "DELETE", json?: object): Promise<T> {
  const res = await fetch("/api/session", {
    method,
    headers: json ? { "Content-Type": "application/json" } : undefined,
    body: json ? JSON.stringify(json) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) throw await toApiError(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const auth = {
  login: (body: LoginBody) => session<Omit<AuthResponse, "token">>("POST", { action: "login", ...body }),
  register: (body: RegisterBody) => session<Omit<AuthResponse, "token">>("POST", { action: "register", ...body }),
  logout: () => session<void>("DELETE"),
};

/* ---------- Typed endpoints ---------- */
const id = encodeURIComponent;

export const api = {
  me: () => request<User>("/me"),
  updateMe: (patch: UserPatch) => request<User>("/me", { method: "PATCH", json: patch }),
  deleteMe: () => request<void>("/me", { method: "DELETE" }),
  exportMe: () => request<unknown>("/me/export"),
  grantConsent: (granted = true) =>
    request<Consent>("/consents", {
      json: { purpose: "ai_processing", policy_version: AI_POLICY_VERSION, granted } satisfies ConsentBody,
    }),

  resumes: () => request<ResumeListItem[]>("/resumes"),
  uploadResume: (file: File, name: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    return request<ResumeWithVersion>("/resumes", { method: "POST", form });
  },
  createFromText: (text: string, name: string) => request<ResumeWithVersion>("/resumes/text", { json: { text, name } }),
  createGuided: (body: GuidedResumeBody) => request<ResumeWithVersion>("/resumes/guided", { json: body }),
  resume: (rid: string) => request<ResumeDetail>(`/resumes/${id(rid)}`),
  renameResume: (rid: string, name: string) => request<ResumeDetail>(`/resumes/${id(rid)}`, { method: "PATCH", json: { name } }),
  archiveResume: (rid: string) => request<void>(`/resumes/${id(rid)}`, { method: "DELETE" }),
  version: (rid: string, vid: string) => request<ResumeVersion>(`/resumes/${id(rid)}/versions/${id(vid)}`),
  restoreVersion: (rid: string, vid: string) =>
    request<ResumeVersion>(`/resumes/${id(rid)}/versions/${id(vid)}/restore`, { method: "POST" }),

  createJob: (body: JobBody) => request<JobPosting>("/jobs", { json: body }),

  createWorkflow: (body: WorkflowCreateBody, idempotencyKey: string) =>
    request<Workflow>("/workflows", { json: body, headers: { "Idempotency-Key": idempotencyKey } }),
  workflows: () => request<WorkflowRow[]>("/workflows"),
  workflow: (wid: string, signal?: AbortSignal) => request<WorkflowDetail>(`/workflows/${id(wid)}`, { signal }),
  iterate: (wid: string, body: IterationBody) => request<Workflow>(`/workflows/${id(wid)}/iterations`, { json: body }),
  pauseWorkflow: (wid: string) => request<Workflow>(`/workflows/${id(wid)}/pause`, { method: "POST" }),
  resumeWorkflow: (wid: string) => request<Workflow>(`/workflows/${id(wid)}/resume`, { method: "POST" }),
  cancelWorkflow: (wid: string) => request<Workflow>(`/workflows/${id(wid)}/cancel`, { method: "POST" }),

  decideChange: (gid: string, cid: string, decision: ChangeDecision) =>
    request<ResumeChange>(`/generated/${id(gid)}/changes/${id(cid)}`, { method: "PATCH", json: { decision } }),
  approve: (gid: string) => request<GeneratedResume>(`/generated/${id(gid)}/approve`, { method: "POST" }),
  createExport: (gid: string, kind: ExportKind) => request<ExportResult>(`/generated/${id(gid)}/exports`, { json: { kind } }),
  share: (eid: string, expiresInHours = 72) =>
    request<ShareResult>(`/exports/${id(eid)}/share`, { json: { expires_in_hours: expiresInHours } }),

  applications: () => request<Application[]>("/applications"),
  createApplication: (body: ApplicationBody) => request<Application>("/applications", { json: body }),
  updateApplication: (aid: string, body: Partial<ApplicationBody>) =>
    request<Application>(`/applications/${id(aid)}`, { method: "PATCH", json: body }),
  deleteApplication: (aid: string) => request<void>(`/applications/${id(aid)}`, { method: "DELETE" }),

  billing: () => request<BillingStatus>("/billing/status"),
  portal: () => request<PortalResult>("/billing/portal", { method: "POST" }),
  checkout: (mode: CheckoutMode) => request<CheckoutResult>("/billing/checkout", { json: { mode } }),
};

/** Opens an export's signed download URL in a new tab. Call synchronously-ish from a click handler. */
export async function exportAndOpen(gid: string, kind: ExportKind): Promise<ExportResult> {
  // Open the tab first so popup blockers treat it as user initiated.
  const win = typeof window !== "undefined" ? window.open("about:blank", "_blank") : null;
  try {
    const result = await api.createExport(gid, kind);
    if (win) {
      win.opener = null;
      win.location.href = result.download_url;
    } else {
      window.location.assign(result.download_url);
    }
    return result;
  } catch (e) {
    win?.close();
    throw e;
  }
}
