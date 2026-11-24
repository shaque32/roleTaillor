"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Check, FilePlus2, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Alert, Button, ButtonLink, Card, CardBody } from "@/components/ui";
import { ResumeUpload } from "@/components/ResumeUpload";
import { TailorForm } from "@/components/TailorForm";

type Step = "consent" | "resume" | "job";
const STEPS: { id: Step; label: string }[] = [
  { id: "consent", label: "AI consent" },
  { id: "resume", label: "Your resume" },
  { id: "job", label: "First job" },
];

export function Onboarding() {
  const params = useSearchParams();
  const router = useRouter();
  const initialStep = (params.get("step") as Step | null) ?? "consent";
  const [step, setStep] = useState<Step>(STEPS.some((s) => s.id === initialStep) ? initialStep : "consent");
  const [versionId, setVersionId] = useState<string | undefined>(params.get("version") ?? undefined);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idx = STEPS.findIndex((s) => s.id === step);

  async function consent() {
    setBusy(true);
    setError(null);
    try {
      await api.grantConsent(true);
      setStep("resume");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your consent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <ol className="mb-10 flex items-center gap-2 text-sm" aria-label="Onboarding progress">
        {STEPS.map((s, i) => (
          <li key={s.id} className="flex flex-1 items-center gap-2" aria-current={s.id === step ? "step" : undefined}>
            <span
              className={cx(
                "grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold",
                i < idx ? "bg-brand-600 text-white" : i === idx ? "border-2 border-brand-600 text-brand-700" : "border border-slate-300 text-ink-faint",
              )}
            >
              {i < idx ? <Check className="h-3.5 w-3.5" aria-hidden /> : i + 1}
            </span>
            <span className={cx("hidden sm:inline", i === idx ? "font-medium text-ink" : "text-ink-muted")}>{s.label}</span>
            {i < STEPS.length - 1 && <span className="h-px flex-1 bg-slate-200" aria-hidden />}
          </li>
        ))}
      </ol>

      {step === "consent" && (
        <section aria-labelledby="consent-title" className="space-y-6">
          <div>
            <ShieldCheck className="h-8 w-8 text-brand-600" aria-hidden />
            <h1 id="consent-title" className="mt-3 text-2xl font-semibold tracking-tight">
              How RoleTailor uses AI
            </h1>
            <p className="mt-2 text-sm text-ink-muted">Please read this once. You can withdraw consent any time in Settings.</p>
          </div>
          <Card>
            <CardBody className="space-y-4 text-sm leading-relaxed">
              <div>
                <h2 className="font-semibold">Who processes your resume</h2>
                <p className="mt-1 text-ink-muted">
                  To tailor your resume, its text and the job description are sent to third-party AI model providers: currently
                  Anthropic (Claude) and OpenAI-compatible model APIs. Only the text needed for each step is sent. Your original files
                  stay with RoleTailor.
                </p>
              </div>
              <div>
                <h2 className="font-semibold">Nothing is invented</h2>
                <p className="mt-1 text-ink-muted">
                  We only rephrase and reorder what you already wrote. Every change is checked against your original resume, and
                  skills the job asks for that you don&apos;t evidence are shown to you as gaps, never added.
                </p>
              </div>
              <div>
                <h2 className="font-semibold">Credits</h2>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-muted">
                  <li>Your first 10 tailored resumes are free.</li>
                  <li>Iterations on the same job are always free.</li>
                  <li>Failed generations never count against you.</li>
                </ul>
              </div>
            </CardBody>
          </Card>
          <label className="flex items-start gap-3 text-sm">
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600" />
            <span>I agree to my resume and job descriptions being processed by these AI providers to tailor my resume.</span>
          </label>
          {error && <Alert tone="error">{error}</Alert>}
          <div className="flex items-center gap-3">
            <Button onClick={consent} disabled={!agreed} loading={busy}>
              Agree and continue
            </Button>
            <Link href="/dashboard" className="text-sm text-ink-muted hover:text-ink">
              Not now
            </Link>
          </div>
        </section>
      )}

      {step === "resume" && (
        <section aria-labelledby="resume-title" className="space-y-6">
          <div>
            <h1 id="resume-title" className="text-2xl font-semibold tracking-tight">
              Add your resume
            </h1>
            <p className="mt-2 text-sm text-ink-muted">Upload your current resume. We&apos;ll show you what we read so you can check it.</p>
          </div>
          <ResumeUpload
            submitLabel="Upload and continue"
            onUploaded={({ version }) => {
              setVersionId(version.id);
              setStep("job");
            }}
          />
          <div className="flex items-center gap-4 border-t border-slate-200 pt-6">
            <FilePlus2 className="h-5 w-5 text-ink-faint" aria-hidden />
            <p className="flex-1 text-sm text-ink-muted">No resume handy? Build one step by step.</p>
            <ButtonLink href="/resumes/new?from=onboarding" variant="secondary" size="sm">
              Create from scratch
            </ButtonLink>
          </div>
        </section>
      )}

      {step === "job" && (
        <section aria-labelledby="job-title" className="space-y-6">
          <div>
            <h1 id="job-title" className="text-2xl font-semibold tracking-tight">
              Paste your first job
            </h1>
            <p className="mt-2 text-sm text-ink-muted">Add the role you&apos;re applying for and we&apos;ll start tailoring.</p>
          </div>
          <TailorForm initialVersionId={versionId} />
          <button onClick={() => router.push("/dashboard")} className="text-sm text-ink-muted hover:text-ink">
            Skip for now
          </button>
        </section>
      )}
    </div>
  );
}
