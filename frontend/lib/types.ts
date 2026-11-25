/**
 * Types mirroring docs/api-v1.md. Where the contract leaves a shape open, the
 * fields follow db/migrations/001 and backend domain models, and optional
 * fields are marked `?` so the UI degrades gracefully.
 */

export type UUID = string;
export type ISODate = string;

/* ---------- Errors ---------- */
export interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

/* ---------- Auth and profile ---------- */
export interface Address {
  line1?: string;
  city?: string;
  region?: string;
  postal_code?: string;
  country?: string;
}

export type ResumeTone = "professional" | "confident" | "concise" | "warm";
export type AtsPreference = "balanced" | "ats_first" | "human_first";
export type TechnicalDepth = "low" | "medium" | "high";

export interface User {
  id: UUID;
  email: string;
  email_verified_at: string | null;
  full_name: string;
  address?: Address | null;
  contact_number?: string | null;
  linkedin_url?: string | null;
  preferred_page_limit?: number;
  industry_focus?: string | null;
  resume_tone?: string | null;
  ats_preference?: string | null;
  technical_depth?: string | null;
  preferred_template_id?: UUID | null;
  created_at?: ISODate;
}

export type UserPatch = Partial<
  Pick<
    User,
    | "full_name"
    | "address"
    | "contact_number"
    | "linkedin_url"
    | "preferred_page_limit"
    | "industry_focus"
    | "resume_tone"
    | "ats_preference"
    | "technical_depth"
    | "preferred_template_id"
  >
>;

export interface Organization {
  id: UUID;
  name: string;
  free_generation_limit?: number;
}

export interface AuthResponse {
  token: string;
  user: User;
  organization: Organization;
}

export interface RegisterBody {
  email: string;
  password: string;
  full_name: string;
}

export interface LoginBody {
  email: string;
  password: string;
  device_label?: string;
}

export interface ConsentBody {
  purpose: "ai_processing";
  policy_version: string;
  granted: boolean;
}

export interface Consent {
  id: UUID;
  purpose: string;
  policy_version: string;
  granted: boolean;
  recorded_at: ISODate;
}

/* ---------- Resumes ---------- */
export type ResumeOrigin = "upload" | "guided";

export interface Block {
  id: string;
  kind?: "paragraph" | "table_paragraph" | "text_line";
  text: string;
  style_name?: string | null;
  is_list_item?: boolean;
  is_heading?: boolean;
  editable?: boolean;
}

export interface ExtractionFinding {
  code: string;
  detail: string;
  severity?: "info" | "warn" | "error";
  block_id?: string | null;
}

export interface ResumeVersionSummary {
  id: UUID;
  version_number: number;
  created_at: ISODate;
}

export type ResumeSourceFormat = "docx" | "pdf" | "guided" | "text";

export interface ResumeVersion extends ResumeVersionSummary {
  resume_id?: UUID;
  source_format?: ResumeSourceFormat | null;
  parent_version_id?: UUID | null;
  blocks: Block[];
  findings: ExtractionFinding[];
  layout_metadata: Record<string, unknown>;
}

export interface ResumeListItem {
  id: UUID;
  name: string;
  origin: ResumeOrigin;
  created_at: ISODate;
  latest_version: ResumeVersionSummary | null;
}

export interface ResumeDetail {
  id: UUID;
  name: string;
  origin: ResumeOrigin;
  created_at: ISODate;
  archived_at?: ISODate | null;
  versions: ResumeVersionSummary[];
}

export interface ResumeWithVersion {
  resume: ResumeListItem | ResumeDetail;
  version: ResumeVersion;
}

/* Guided builder */
export type SectionKind =
  | "summary"
  | "experience"
  | "education"
  | "skills"
  | "certifications"
  | "projects"
  | "achievements"
  | "other";

export interface GuidedContact {
  full_name: string;
  email?: string;
  phone?: string;
  location?: string;
  links: string[];
}

export interface ExperienceItem {
  company: string;
  title: string;
  location?: string;
  start?: string;
  end?: string;
  bullets: string[];
}
export interface EducationItem {
  institution: string;
  degree?: string;
  field?: string;
  start?: string;
  end?: string;
  details?: string;
}
export interface CertificationItem {
  name: string;
  issuer?: string;
  date?: string;
}
export interface ProjectItem {
  name: string;
  link?: string;
  description?: string;
  bullets: string[];
}
export interface TextItem {
  text: string;
}

export type GuidedItem = ExperienceItem | EducationItem | CertificationItem | ProjectItem | TextItem;

export interface GuidedSection {
  kind: SectionKind;
  title: string;
  items: GuidedItem[];
}

export interface ResumeTextBody {
  text: string;
  name: string;
}

export interface GuidedResumeBody {
  name: string;
  contact: GuidedContact;
  sections: GuidedSection[];
}

/* ---------- Jobs ---------- */
export interface JobBody {
  source_url?: string;
  description?: string;
  title?: string;
  company?: string;
}

export interface JobPosting {
  id: UUID;
  source_url?: string | null;
  title?: string | null;
  company?: string | null;
  description?: string | null;
  created_at?: ISODate;
}

/* ---------- Workflows ---------- */
export type WorkflowStatus = "draft" | "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface Workflow {
  id: UUID;
  status: WorkflowStatus;
  page_limit?: number;
  source_resume_version_id?: UUID;
  job_posting_id?: UUID;
  created_at?: ISODate;
  updated_at?: ISODate;
  /** Progress hint while running (assumed, optional). */
  stage?: string | null;
  /** User-facing recovery message on failure (assumed name; see README). */
  recovery_message?: string | null;
  error?: { code?: string; message?: string } | null;
  resume_name?: string | null;
  target_role?: string | null;
  company?: string | null;
}

export interface WorkflowCreateBody {
  resume_version_id: UUID;
  job_posting_id: UUID;
  page_limit?: number;
  accept_paid_usage?: boolean;
}

export interface WorkflowRow {
  id: UUID;
  status: WorkflowStatus;
  resume_name: string | null;
  target_role: string | null;
  company: string | null;
  ats_score: number | null;
  simulation_score: number | null;
  created_at: ISODate;
}

export interface Scores {
  ats: number;
  job_alignment: number;
  keyword_relevance: number;
  formatting: number;
}

export type InterviewLikelihood = "low" | "moderate" | "high";

export interface HiringManagerFeedback {
  overall: number;
  technical_alignment: number;
  leadership: number;
  domain_alignment: number;
  communication: number;
  interview_likelihood: InterviewLikelihood;
  strengths: string[];
  weaknesses: string[];
  suggested_improvements: string[];
  competitive_positioning?: string;
}

export interface GeneratedResume {
  id: UUID;
  workflow_id?: UUID;
  iteration: number;
  resume_version_id: UUID;
  ats_score: number | null;
  job_alignment_score: number | null;
  keyword_relevance_score: number | null;
  formatting_score: number | null;
  simulation_score: number | null;
  simulated_feedback?: HiringManagerFeedback | null;
  approved_at: ISODate | null;
  created_at?: ISODate;
}

export type ChangeDecision = "accepted" | "rejected" | "pending";

export interface ResumeChange {
  id: UUID;
  generated_resume_id?: UUID;
  block_path: string;
  prior_text: string | null;
  proposed_text: string | null;
  reason: string | null;
  prioritized_keywords: string[];
  decision: ChangeDecision;
  decided_at?: ISODate | null;
}

/** Gaps are JD keywords with no evidence in the resume. Strings per TailoringPlan.gaps; objects tolerated. */
export type Gap = string | { term: string; importance?: "must" | "should" | "nice"; category?: string };

export interface WorkflowDetail {
  workflow: Workflow;
  latest: GeneratedResume | null;
  scores_before: Scores | null;
  gaps: Gap[];
  feedback: HiringManagerFeedback | null;
  changes: ResumeChange[];
}

export interface IterationBody {
  focus_block_ids?: string[];
  instructions?: string;
}

/* ---------- Exports ---------- */
export type ExportKind = "docx" | "pdf" | "ats_report" | "feedback_report";

export interface ExportResult {
  export_id: UUID;
  download_url: string;
  expires_at: ISODate;
}

export interface ShareResult {
  url: string;
}

/* ---------- Applications ---------- */
export type ApplicationStatus = "saved" | "applied" | "interviewing" | "offered" | "rejected" | "withdrawn" | "accepted";

export interface ApplicationBody {
  company: string;
  role_title: string;
  status: ApplicationStatus;
  applied_at?: ISODate | null;
  reminder_at?: ISODate | null;
  notes?: string | null;
  job_posting_id?: UUID | null;
  resume_version_id?: UUID | null;
}

export interface Application extends ApplicationBody {
  id: UUID;
  created_at?: ISODate;
}

/* ---------- Billing ---------- */
export interface Subscription {
  status: string;
  current_period_end?: ISODate | null;
  cancel_at_period_end?: boolean;
}

export interface BillingStatus {
  free_used: number;
  free_limit: number;
  subscription: Subscription | null;
  pay_per_use_credits: number;
}

export type CheckoutMode = "subscription" | "pay_per_use";

export interface CheckoutResult {
  checkout_url: string;
}

export interface PortalResult {
  portal_url: string;
}

export interface PaymentOption {
  mode: CheckoutMode;
  amount_minor?: number;
  currency?: string;
  label?: string;
}
