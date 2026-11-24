"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { BillingStatus, ResumeVersionSummary } from "@/lib/types";
import { formatDate, cx } from "@/lib/format";
import { Alert, Button, Input, Select, Skeleton, Textarea, ButtonLink } from "@/components/ui";
import { PaymentDialog } from "./PaymentDialog";

type JobMode = "url" | "paste";
const PAGE_OPTIONS = [
  { value: 1, label: "1 page", hint: "Early career or concise" },
  { value: 2, label: "2 pages", hint: "Recommended for most roles" },
  { value: 3, label: "3+ pages", hint: "Senior, academic or federal" },
];

export function TailorForm({ initialVersionId, defaultPageLimit = 2 }: { initialVersionId?: string; defaultPageLimit?: number }) {
  const router = useRouter();
  const resumes = useResource(() => api.resumes());
  const [resumeId, setResumeId] = useState<string>("");
  const [versions, setVersions] = useState<ResumeVersionSummary[] | null>(null);
  const [versionId, setVersionId] = useState<string>(initialVersionId ?? "");

  const [jobMode, setJobMode] = useState<JobMode>("url");
  const [jobUrl, setJobUrl] = useState("");
  const [jobText, setJobText] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [pageLimit, setPageLimit] = useState(Math.min(3, Math.max(1, defaultPageLimit)));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<React.ReactNode>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const jobCache = useRef<{ key: string; id: string } | null>(null);
  const pasteRef = useRef<HTMLTextAreaElement>(null);

  // Default selection: resume holding the initial version, else the first resume.
  useEffect(() => {
    const list = resumes.data;
    if (!list || resumeId) return;
    const match = initialVersionId ? list.find((r) => r.latest_version?.id === initialVersionId) : undefined;
    const first = match ?? list[0];
    if (first) {
      setResumeId(first.id);
      if (!initialVersionId && first.latest_version) setVersionId(first.latest_version.id);
    }
  }, [resumes.data, resumeId, initialVersionId]);

  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;
    setVersions(null);
    api
      .resume(resumeId)
      .then((r) => {
        if (cancelled) return;
        const sorted = [...r.versions].sort((a, b) => b.version_number - a.version_number);
        setVersions(sorted);
        setVersionId((cur) => (sorted.some((v) => v.id === cur) ? cur : (sorted[0]?.id ?? "")));
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [resumeId]);

  async function ensureJob(): Promise<string> {
    const body =
      jobMode === "url"
        ? { source_url: jobUrl.trim(), title: title.trim() || undefined, company: company.trim() || undefined }
        : { description: jobText.trim(), title: title.trim() || undefined, company: company.trim() || undefined };
    const key = JSON.stringify(body);
    if (jobCache.current?.key === key) return jobCache.current.id;
    const job = await api.createJob(body);
    jobCache.current = { key, id: job.id };
    return job.id;
  }

  async function start(acceptPaid = false) {
    setError(null);
    setNotice(null);
    if (!versionId) return setError("Choose a resume to tailor.");
    if (jobMode === "url" && !/^https?:\/\/\S+$/i.test(jobUrl.trim())) return setError("Enter the full job link, starting with https://");
    if (jobMode === "paste" && jobText.trim().length < 80) return setError("Paste the full job description (at least a few sentences).");

    setBusy(true);
    let jobId: string;
    try {
      jobId = await ensureJob();
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError && e.code === "job_url_unreadable") {
        setJobMode("paste");
        setNotice("We couldn't read that job page (some sites block automated access). Please paste the job description instead.");
        setTimeout(() => pasteRef.current?.focus(), 0);
        return;
      }
      return setError(e instanceof Error ? e.message : "Couldn't save the job.");
    }

    try {
      const wf = await api.createWorkflow(
        { resume_version_id: versionId, job_posting_id: jobId, page_limit: pageLimit, accept_paid_usage: acceptPaid || undefined },
        crypto.randomUUID(),
      );
      router.push(`/tailor/${wf.id}`);
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError && e.status === 402) {
        if (acceptPaid) throw e; // surfaced inside the dialog
        setBilling(await api.billing().catch(() => null));
        setPayOpen(true);
        return;
      }
      if (e instanceof ApiError && e.status === 428) {
        return setError(
          <>
            Before we can tailor, we need your consent for AI processing.{" "}
            <Link href="/onboarding" className="font-medium underline">
              Review and consent
            </Link>
          </>,
        );
      }
      if (acceptPaid) throw e;
      setError(e instanceof Error ? e.message : "Couldn't start tailoring.");
    }
  }

  if (resumes.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (resumes.error) return <Alert tone="error">{resumes.error.message}</Alert>;
  if (!resumes.data?.length) {
    return (
      <Alert tone="info" title="Add a resume first">
        <div className="mt-2 flex gap-2">
          <ButtonLink href="/resumes" size="sm">
            Upload a resume
          </ButtonLink>
          <ButtonLink href="/resumes/new" size="sm" variant="secondary">
            Build one
          </ButtonLink>
        </div>
      </Alert>
    );
  }

  return (
    <form
      className="space-y-8"
      onSubmit={(e) => {
        e.preventDefault();
        void start(false);
      }}
    >
      <fieldset className="space-y-4">
        <legend className="text-sm font-semibold text-ink">1. Resume</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Resume" value={resumeId} onChange={(e) => setResumeId(e.target.value)}>
            {resumes.data.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </Select>
          <Select label="Version" value={versionId} onChange={(e) => setVersionId(e.target.value)} disabled={!versions?.length}>
            {versions === null && <option>Loading…</option>}
            {versions?.map((v, i) => (
              <option key={v.id} value={v.id}>
                v{v.version_number} · {formatDate(v.created_at)}
                {i === 0 ? " (latest)" : ""}
              </option>
            ))}
          </Select>
        </div>
      </fieldset>

      <fieldset className="space-y-4">
        <legend className="text-sm font-semibold text-ink">2. Job</legend>
        <div role="tablist" aria-label="How to add the job" className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-0.5">
          {(["url", "paste"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={jobMode === m}
              onClick={() => setJobMode(m)}
              className={cx("rounded px-3 py-1.5 text-sm", jobMode === m ? "bg-white font-medium shadow-sm" : "text-ink-muted")}
            >
              {m === "url" ? "Job link" : "Paste description"}
            </button>
          ))}
        </div>
        {notice && <Alert tone="warning">{notice}</Alert>}
        {jobMode === "url" ? (
          <Input
            label="Job posting URL"
            type="url"
            inputMode="url"
            placeholder="https://company.com/careers/role"
            value={jobUrl}
            onChange={(e) => setJobUrl(e.target.value)}
          />
        ) : (
          <Textarea
            ref={pasteRef}
            label="Job description"
            rows={10}
            placeholder="Paste the full job description, including responsibilities and requirements."
            value={jobText}
            onChange={(e) => setJobText(e.target.value)}
          />
        )}
        <details className="group">
          <summary className="cursor-pointer text-sm text-ink-muted hover:text-ink">Add role title and company (optional)</summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Input label="Role title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Input label="Company" value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
        </details>
      </fieldset>

      <fieldset>
        <legend className="mb-3 text-sm font-semibold text-ink">3. Length</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {PAGE_OPTIONS.map((o) => (
            <label
              key={o.value}
              className={cx(
                "cursor-pointer rounded-md border px-4 py-3 text-sm focus-within:ring-2 focus-within:ring-brand-100",
                pageLimit === o.value ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300",
              )}
            >
              <input type="radio" name="page_limit" value={o.value} checked={pageLimit === o.value} onChange={() => setPageLimit(o.value)} className="sr-only" />
              <span className="block font-medium">{o.label}</span>
              <span className="block text-xs text-ink-muted">{o.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" loading={busy}>
          Start tailoring
        </Button>
        <p className="text-xs text-ink-muted">We only rephrase what&apos;s already in your resume. Nothing is invented.</p>
      </div>

      <PaymentDialog open={payOpen} onClose={() => setPayOpen(false)} billing={billing} onAccept={() => start(true)} />
    </form>
  );
}
