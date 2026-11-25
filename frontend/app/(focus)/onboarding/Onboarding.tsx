"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { FilePlus2 } from "lucide-react";
import { Button, ButtonLink, Card, Stepper } from "@/components/ui";
import { ResumeUpload } from "@/components/ResumeUpload";
import { TailorForm } from "@/components/TailorForm";

// AI consent is not a step here: the tailoring form asks for it right before the first tailoring.
type Step = "resume" | "job";
const STEPS: { id: Step; label: string }[] = [
  { id: "resume", label: "Your resume" },
  { id: "job", label: "First job" },
];

export function Onboarding() {
  const params = useSearchParams();
  const router = useRouter();
  const initialStep = (params.get("step") as Step | null) ?? "resume";
  const [step, setStep] = useState<Step>(STEPS.some((s) => s.id === initialStep) ? initialStep : "resume");
  const [versionId, setVersionId] = useState<string | undefined>(params.get("version") ?? undefined);
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

  const h1 = "text-3xl font-semibold tracking-tight focus:outline-none";

  return (
    <div>
      <Stepper aria-label="Getting started" steps={STEPS} current={idx} className="mb-8" />

      <Card className="animate-fade-in p-6 sm:p-8" key={step}>
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
              canLeave={false}
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
