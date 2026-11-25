"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { FilePlus2 } from "lucide-react";
import { api } from "@/lib/api";
import { setConsentHint } from "@/lib/consent";
import { Alert, Button, ButtonLink, Card, Checkbox, Stepper } from "@/components/ui";
import { ConsentPoints } from "@/components/ConsentDialog";
import { ResumeUpload } from "@/components/ResumeUpload";
import { TailorForm } from "@/components/TailorForm";

type Step = "consent" | "resume" | "job";
const STEPS: { id: Step; label: string }[] = [
  { id: "consent", label: "Privacy" },
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
  const headingRef = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);

  // Move focus to the step heading when the step changes (not on first paint).
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  async function consent() {
    setBusy(true);
    setError(null);
    try {
      await api.grantConsent(true);
      setConsentHint("granted");
      setStep("resume");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your consent.");
    } finally {
      setBusy(false);
    }
  }

  function decideLater() {
    setConsentHint("declined");
    setStep("resume");
  }

  const h1 = "text-3xl font-semibold tracking-tight focus:outline-none";

  return (
    <div>
      <Stepper aria-label="Getting started" steps={STEPS} current={idx} className="mb-8" />

      <Card className="animate-fade-in p-6 sm:p-8" key={step}>
        {step === "consent" && (
          <section aria-labelledby="consent-title" className="space-y-6">
            <div>
              <h1 id="consent-title" ref={headingRef} tabIndex={-1} className={h1}>
                Before we start: how we use AI
              </h1>
              <p className="mt-2 text-sm text-ink-muted">Takes 20 seconds. You can change your mind any time in Settings.</p>
            </div>
            <ConsentPoints />
            <div className="border-t border-line pt-6">
              <Checkbox
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
                label="I agree to my resume and job descriptions being processed by these AI providers to tailor my resume."
              />
            </div>
            {error && <Alert tone="error">{error}</Alert>}
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <Button size="lg" onClick={consent} disabled={!agreed} loading={busy}>
                  Agree and continue
                </Button>
                <Button variant="ghost" size="lg" onClick={decideLater}>
                  Decide later
                </Button>
              </div>
              <p className="mt-3 text-sm text-ink-muted">If you skip this, we&apos;ll ask again right before your first tailoring.</p>
            </div>
          </section>
        )}

        {step === "resume" && (
          <section aria-labelledby="resume-title" className="space-y-6">
            <div>
              <h1 id="resume-title" ref={headingRef} tabIndex={-1} className={h1}>
                Add your resume
              </h1>
              <p className="mt-2 text-sm text-ink-muted">Upload what you have. You&apos;ll see exactly what we read.</p>
            </div>
            <ResumeUpload
              submitLabel="Upload and continue"
              onUploaded={({ version }) => {
                setVersionId(version.id);
                setStep("job");
              }}
            />
            <Card variant="sunken" className="flex flex-wrap items-center gap-4 p-4">
              <FilePlus2 className="h-5 w-5 shrink-0 text-ink-muted" aria-hidden />
              <div className="min-w-0 flex-1 basis-40">
                <p className="text-sm font-medium text-ink">No resume handy?</p>
                <p className="text-sm text-ink-muted">Build one step by step.</p>
              </div>
              <ButtonLink href="/resumes/new?from=onboarding" variant="secondary" size="sm">
                Build from scratch
              </ButtonLink>
            </Card>
          </section>
        )}

        {step === "job" && (
          <section aria-labelledby="job-title" className="space-y-6">
            <div>
              <h1 id="job-title" ref={headingRef} tabIndex={-1} className={h1}>
                Which job are you going for?
              </h1>
              <p className="mt-2 text-sm text-ink-muted">Paste the link or the description. We&apos;ll do the rest.</p>
            </div>
            <TailorForm initialVersionId={versionId} />
            <Button variant="ghost" onClick={() => router.push("/dashboard")}>
              Skip for now
            </Button>
          </section>
        )}
      </Card>
    </div>
  );
}
