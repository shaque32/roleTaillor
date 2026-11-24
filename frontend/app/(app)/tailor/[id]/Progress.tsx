"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import type { WorkflowStatus } from "@/lib/types";
import { cx } from "@/lib/format";
import { Card, CardBody, Spinner } from "@/components/ui";

const STEPS = [
  { key: "structure", label: "Reading your resume" },
  { key: "analyze", label: "Understanding the job" },
  { key: "plan", label: "Matching your experience to the role" },
  { key: "rewrite", label: "Rephrasing with your own facts" },
  { key: "validate", label: "Checking nothing was invented" },
  { key: "score", label: "Scoring and simulating a hiring manager review" },
];

/** Calm progress state. Uses workflow.stage when the backend provides it, else estimates from elapsed time. */
export function Progress({ status, stage, startedAt, iterating }: { status: WorkflowStatus; stage?: string | null; startedAt: number; iterating: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const byStage = stage ? STEPS.findIndex((s) => stage.toLowerCase().includes(s.key)) : -1;
  const estimated = status === "queued" ? 0 : Math.min(STEPS.length - 1, Math.floor((now - startedAt) / 9000));
  const current = byStage >= 0 ? byStage : estimated;

  return (
    <Card className="mb-10">
      <CardBody className="py-8">
        <div className="mx-auto max-w-md">
          <div className="flex items-center gap-3">
            <Spinner className="h-5 w-5 text-brand-600" />
            <h2 className="text-base font-semibold" aria-live="polite">
              {status === "queued" ? "Queued, starting shortly…" : iterating ? "Regenerating selected changes…" : "Tailoring your resume…"}
            </h2>
          </div>
          <p className="mt-1 pl-8 text-sm text-ink-muted">This usually takes under a minute. You can leave this page; we&apos;ll keep working.</p>
          <ol className="mt-6 space-y-3 pl-8">
            {STEPS.map((s, i) => (
              <li key={s.key} className={cx("flex items-center gap-3 text-sm", i < current ? "text-ink-muted" : i === current ? "font-medium text-ink" : "text-ink-faint")}>
                <span className={cx("grid h-5 w-5 place-items-center rounded-full", i < current ? "bg-brand-100 text-brand-700" : i === current ? "border-2 border-brand-500" : "border border-slate-300")}>
                  {i < current && <Check className="h-3 w-3" aria-hidden />}
                </span>
                {s.label}
              </li>
            ))}
          </ol>
        </div>
      </CardBody>
    </Card>
  );
}
