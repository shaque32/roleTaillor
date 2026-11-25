"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, FileText, Link2, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { BillingStatus, ResumeVersionSummary } from "@/lib/types";
import { formatDate } from "@/lib/format";
import { isReading, isUnavailable } from "@/lib/processing";
import { Alert, Button, ButtonLink, ChoiceCards, Disclosure, Input, Select, Skeleton, Textarea } from "@/components/ui";
import { ConsentDialog } from "@/components/ConsentDialog";
import { PaymentDialog } from "./PaymentDialog";

const PAGE_OPTIONS = [
  { value: "1", label: "1 page", description: "Early career or concise" },
  {
    value: "2",
    label: "2 pages",
    description: "Right for most roles",
    badge: "Recommended",
  },
  { value: "3", label: "3+ pages", description: "Senior, academic or federal" },
];
const MIN_DESCRIPTION = 80;

export function TailorForm({ initialVersionId, defaultPageLimit = 2 }: { initialVersionId?: string; defaultPageLimit?: number }) {
  const router = useRouter();
  const resumes = useResource(() => api.resumes());
  const [resumeId, setResumeId] = useState<string>("");
  const [versions, setVersions] = useState<ResumeVersionSummary[] | null>(null);
  const [versionId, setVersionId] = useState<string>(initialVersionId ?? "");
  const [changing, setChanging] = useState(false);
  const [pickVersion, setPickVersion] = useState(false);

  const [jobInput, setJobInput] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [pageLimit, setPageLimit] = useState(Math.min(3, Math.max(1, defaultPageLimit)));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<React.ReactNode>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const jobCache = useRef<{ key: string; id: string } | null>(null);
  const jobRef = useRef<HTMLTextAreaElement>(null);

  const trimmed = jobInput.trim();
  const isUrl = /^https?:\/\/\S+$/i.test(trimmed);

  // Default selection: resume holding the initial version, else the first resume.
  useEffect(() => {
    const list = resumes.data?.filter((r) => !isUnavailable(r));
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
    const extra = {
      title: title.trim() || undefined,
      company: company.trim() || undefined,
    };
    const body = isUrl ? { source_url: trimmed, ...extra } : { description: trimmed, ...extra };
    const key = JSON.stringify(body);
    if (jobCache.current?.key === key) return jobCache.current.id;
    const job = await api.createJob(body);
    jobCache.current = { key, id: job.id };
    return job.id;
  }

  async function start(acceptPaid = false) {
    setError(null);
    setJobError(null);
    setNotice(null);
    if (!versionId) return setError("Choose a resume to tailor.");
    if (!trimmed) {
      jobRef.current?.focus();
      return setJobError("Paste the job link or description.");
    }
    if (!isUrl && trimmed.length < MIN_DESCRIPTION) {
      jobRef.current?.focus();
      return setJobError("Paste the full job description (at least a few sentences).");
    }

    setBusy(true);
    let jobId: string;
    try {
      jobId = await ensureJob();
    } catch (e) {
      setBusy(false);
      if (e instanceof ApiError && e.code === "job_url_unreadable") {
        setJobInput("");
        setNotice("We couldn't read that page (some sites block us). Paste the job description text here instead.");
        setTimeout(() => jobRef.current?.focus(), 0);
        return;
      }
      return setError(e instanceof Error ? e.message : "Couldn't save the job.");
    }

    try {
      const wf = await api.createWorkflow(
        {
          resume_version_id: versionId,
          job_posting_id: jobId,
          page_limit: pageLimit,
          accept_paid_usage: acceptPaid || undefined,
        },
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
        setConsentOpen(true);
        return;
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
  // Scans still being read (or that could not be read) have no version to tailor yet.
  const all = resumes.data ?? [];
  const list = all.filter((r) => !isUnavailable(r));
  if (!list.length) {
    const waiting = all.some(isReading);
    return (
      <div className="rounded-lg bg-surface-sunken px-5 py-6 text-center">
        <h2 className="text-base font-semibold">{waiting ? "Your scan is still being read" : "Add a resume first"}</h2>
        <p className="mt-1 text-sm text-ink-muted">
          {waiting
            ? "You can tailor it as soon as it's ready. Check your resumes in a minute."
            : "Tailoring starts from a resume you already have, or one you build here."}
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <ButtonLink href="/resumes">{waiting ? "Go to resumes" : "Upload a resume"}</ButtonLink>
          <ButtonLink href="/resumes/new" variant="secondary">
            Build one
          </ButtonLink>
        </div>
      </div>
    );
  }

  const current = list.find((r) => r.id === resumeId);
  const selected = versions?.find((v) => v.id === versionId) ?? (current?.latest_version?.id === versionId ? current.latest_version : null);
  const latestId = versions?.[0]?.id ?? current?.latest_version?.id;
  const isLatest = Boolean(selected) && selected?.id === latestId;
  const versionLabel = selected ? `v${selected.version_number} · ${formatDate(selected.created_at)}` : "";
  const collapsed = (list.length === 1 || Boolean(initialVersionId)) && !changing;
  const latestOf = (r: (typeof list)[number]) =>
    r.latest_version ? `v${r.latest_version.version_number} · added ${formatDate(r.created_at)}` : `added ${formatDate(r.created_at)}`;

  return (
    <form
      className="space-y-8"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void start(false);
      }}
    >
      <fieldset>
        <legend className="mb-3 text-base font-semibold text-ink">The job</legend>
        <div className="space-y-4">
          {notice && <Alert tone="warning">{notice}</Alert>}
          <Textarea
            ref={jobRef}
            autoGrow
            rows={3}
            label="Job link or description"
            placeholder="Paste a link (https://…) or the full job description"
            value={jobInput}
            onChange={(e) => {
              setJobInput(e.target.value);
              setJobError(null);
            }}
            error={jobError ?? undefined}
          />
          <p aria-live="polite" className="-mt-2 flex items-center gap-1.5 text-sm text-ink-muted">
            {!trimmed ? (
              "Either works. A pasted description is the most reliable."
            ) : isUrl ? (
              <>
                <Link2 className="h-4 w-4 shrink-0 text-brand-600" aria-hidden /> Link detected. We&apos;ll read the posting for you.
              </>
            ) : (
              <>
                Description · {trimmed.length.toLocaleString()} characters
                {trimmed.length < MIN_DESCRIPTION && " · keep going, we need a few sentences"}
              </>
            )}
          </p>
          <Disclosure summary="Add role title and company (optional)">
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="Role title" value={title} onChange={(e) => setTitle(e.target.value)} />
              <Input label="Company" value={company} onChange={(e) => setCompany(e.target.value)} />
            </div>
          </Disclosure>
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-3 text-base font-semibold text-ink">Your resume</legend>
        <div className="space-y-4">
          {collapsed ? (
            <div className="flex items-center gap-3 rounded-lg bg-surface-sunken px-4 py-3">
              <FileText className="h-5 w-5 shrink-0 text-brand-600" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="break-words font-medium">{current?.name ?? "Resume"}</p>
                {selected ? (
                  <p className="text-sm text-ink-muted">{isLatest ? `Latest version (${versionLabel})` : `Version ${versionLabel}`}</p>
                ) : (
                  <Skeleton className="mt-1 h-4 w-40" />
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={() => setChanging(true)}>
                Change
              </Button>
            </div>
          ) : (
            <>
              {list.length <= 4 ? (
                <ChoiceCards
                  columns={2}
                  name="resume"
                  label="Resume"
                  value={resumeId}
                  onChange={setResumeId}
                  options={list.map((r) => ({
                    value: r.id,
                    label: r.name,
                    description: latestOf(r),
                  }))}
                />
              ) : (
                <Select
                  label="Resume"
                  value={resumeId}
                  onChange={setResumeId}
                  options={list.map((r) => ({
                    value: r.id,
                    label: r.name,
                    description: latestOf(r),
                  }))}
                />
              )}
              {versions === null ? (
                <Skeleton className="h-12" />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <p className="text-ink-muted">
                      {isLatest ? `Using the latest version (v${selected?.version_number}).` : `Using ${versionLabel}.`}
                    </p>
                    {versions.length > 1 && !pickVersion && (
                      <Button variant="ghost" size="sm" className="!text-brand-700" onClick={() => setPickVersion(true)}>
                        Pick an older version
                      </Button>
                    )}
                  </div>
                  {pickVersion && versions.length > 1 && (
                    <Select
                      label="Version"
                      value={versionId}
                      onChange={setVersionId}
                      options={versions.map((v, i) => ({
                        value: v.id,
                        label: `v${v.version_number} · ${formatDate(v.created_at)}`,
                        description: i === 0 ? "Latest" : undefined,
                      }))}
                    />
                  )}
                </>
              )}
            </>
          )}
        </div>
      </fieldset>

      <ChoiceCards
        columns={3}
        name="page_limit"
        label="Length"
        value={String(pageLimit)}
        onChange={(v) => setPageLimit(Number(v))}
        options={PAGE_OPTIONS}
      />

      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
        <Button type="submit" size="lg" loading={busy} className="w-full sm:w-auto">
          Start tailoring <ArrowRight className="h-4 w-4" aria-hidden />
        </Button>
        <p className="flex items-start gap-1.5 text-sm text-ink-muted">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" aria-hidden />
          We only rephrase what&apos;s already in your resume. Nothing is invented.
        </p>
      </div>

      <PaymentDialog open={payOpen} onClose={() => setPayOpen(false)} billing={billing} onAccept={() => start(true)} />
      <ConsentDialog
        open={consentOpen}
        onClose={() => setConsentOpen(false)}
        onGranted={() => start(false)}
        confirmLabel="Agree and start tailoring"
      />
    </form>
  );
}
