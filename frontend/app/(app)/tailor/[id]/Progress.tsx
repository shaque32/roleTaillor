"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { WorkflowStatus } from "@/lib/types";
import { Button, Card, Stepper } from "@/components/ui";
import { DotBackground } from "@/components/fx/DotBackground";
import { ShinyText } from "@/components/fx/ShinyText";

const STEPS = [
  { key: "structure", label: "Reading your resume" },
  { key: "analyze", label: "Understanding the job" },
  { key: "plan", label: "Matching your experience to the role" },
  { key: "rewrite", label: "Rephrasing with your own facts" },
  { key: "validate", label: "Checking nothing was invented" },
  { key: "score", label: "Scoring the result" },
];

/** Calm progress state. Uses workflow.stage when the backend provides it, else estimates from elapsed time. */
export function Progress({
  status,
  stage,
  startedAt,
  iterating,
  onPause,
  onCancel,
  compact,
}: {
  status: WorkflowStatus;
  stage?: string | null;
  startedAt: number;
  iterating: boolean;
  onPause?: () => void;
  onCancel?: () => void;
  compact?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const byStage = stage ? STEPS.findIndex((s) => stage.toLowerCase().includes(s.key)) : -1;
  const estimated = status === "queued" ? 0 : Math.min(STEPS.length - 1, Math.floor((now - startedAt) / 9000));
  const current = byStage >= 0 ? byStage : estimated;

  const bar = (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={STEPS.length}
      aria-valuenow={current + 1}
      aria-label="Tailoring progress"
      className="h-1.5 rounded-full bg-surface-sunken"
    >
      <div
        className="h-1.5 rounded-full bg-brand-500 transition-[width] duration-700"
        style={{ width: `${((current + 1) / STEPS.length) * 100}%` }}
      />
    </div>
  );

  return (
    <Card className="relative mb-8 overflow-hidden">
      <DotBackground fade />
      <div className={compact ? "relative px-5 py-5 sm:px-6" : "relative mx-auto max-w-md px-5 py-10 text-center"}>
        <h2 className="text-lg font-semibold" aria-live="polite">
          {status === "queued" ? "Queued, starting shortly…" : iterating ? "Rewriting the selected changes…" : "Tailoring your resume…"}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">Usually under a minute. You can leave this page; we&apos;ll keep going.</p>
        <div className="mt-5">{bar}</div>
        {!compact && (
          <Stepper
            orientation="vertical"
            aria-label="Tailoring steps"
            className="mx-auto mt-6 w-fit max-w-full text-left"
            steps={STEPS.map((s) => ({ id: s.key, label: s.label }))}
            current={current}
            activeLabel={<ShinyText text={STEPS[current]!.label} />}
          />
        )}
        <div className={compact ? "mt-4 flex flex-wrap items-center gap-2" : "mt-6 flex flex-wrap items-center justify-center gap-2"}>
          {onPause && (
            <Button variant="ghost" size="sm" onClick={onPause}>
              Pause
            </Button>
          )}
          {onCancel && (
            <Button variant="ghost" size="sm" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Link
            href="/dashboard"
            className="inline-flex h-9 items-center rounded-lg px-3 text-sm text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
          >
            Back to tailored resumes
          </Link>
        </div>
      </div>
    </Card>
  );
}
