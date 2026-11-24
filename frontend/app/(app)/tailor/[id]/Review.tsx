"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Pause, Play, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { isActive } from "@/lib/format";
import type { WorkflowDetail } from "@/lib/types";
import { Alert, Button, ButtonLink, PageHeader, SkeletonRows, StatusBadge, useToast } from "@/components/ui";
import { Progress } from "./Progress";
import { ScoresPanel } from "./ScoresPanel";
import { SimulationPanel } from "./SimulationPanel";
import { GapsPanel } from "./GapsPanel";
import { ChangeReview } from "./ChangeReview";
import { ExportBar } from "./ExportBar";

const POLL_MS = 2000;

export function Review() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [startedAt] = useState(() => Date.now());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pollKey, setPollKey] = useState(0);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const d = await api.workflow(id, signal);
        setDetail(d);
        setError(null);
        return d;
      } catch (e) {
        if ((e as Error).name === "AbortError") return null;
        setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "Couldn't load this workflow."));
        return null;
      }
    },
    [id],
  );

  // Poll every 2s while queued or running; stop when the tab is hidden to save requests.
  useEffect(() => {
    const ctrl = new AbortController();
    let stopped = false;
    const tick = async () => {
      const d = await load(ctrl.signal);
      if (stopped) return;
      if (d && isActive(d.workflow.status)) {
        timer.current = setTimeout(() => {
          if (stopped) return;
          if (document.visibilityState === "visible") void tick();
          else document.addEventListener("visibilitychange", () => !stopped && void tick(), { once: true });
        }, POLL_MS);
      }
    };
    void tick();
    return () => {
      stopped = true;
      ctrl.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load, pollKey]);

  const restartPolling = () => setPollKey((k) => k + 1);

  async function control(action: "pause" | "resume" | "cancel") {
    try {
      const wf = action === "pause" ? await api.pauseWorkflow(id) : action === "resume" ? await api.resumeWorkflow(id) : await api.cancelWorkflow(id);
      setDetail((d) => (d ? { ...d, workflow: { ...d.workflow, ...wf } } : d));
      restartPolling();
    } catch (e) {
      toast.error(e);
    }
  }

  if (!detail && !error) return <SkeletonRows rows={6} />;
  if (!detail) return <Alert tone="error">{error?.message}</Alert>;

  const { workflow, latest } = detail;
  const role = workflow.target_role ?? "Tailored resume";
  const hasResult = Boolean(latest);

  return (
    <>
      <Link href="/dashboard" className="mb-4 inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Dashboard
      </Link>
      <PageHeader
        title={workflow.company ? `${role} · ${workflow.company}` : role}
        description={
          <span className="inline-flex items-center gap-2">
            <StatusBadge status={workflow.status} />
            {latest && <span>Iteration {latest.iteration}</span>}
            {latest?.approved_at && <span className="text-emerald-700">Approved</span>}
          </span>
        }
        actions={
          <>
            {isActive(workflow.status) && (
              <>
                <Button variant="ghost" size="sm" onClick={() => control("pause")}>
                  <Pause className="h-4 w-4" aria-hidden /> Pause
                </Button>
                <Button variant="ghost" size="sm" onClick={() => control("cancel")}>
                  <X className="h-4 w-4" aria-hidden /> Cancel
                </Button>
              </>
            )}
            {workflow.status === "paused" && (
              <Button variant="secondary" size="sm" onClick={() => control("resume")}>
                <Play className="h-4 w-4" aria-hidden /> Resume
              </Button>
            )}
          </>
        }
      />

      {error && <Alert tone="warning" className="mb-6">Connection hiccup: {error.message} We&apos;ll keep trying.</Alert>}

      {isActive(workflow.status) && <Progress status={workflow.status} stage={workflow.stage} startedAt={startedAt} iterating={hasResult} />}

      {workflow.status === "failed" && (
        <Alert tone="error" title="This tailoring didn't finish" className="mb-8">
          <p>
            {workflow.recovery_message ??
              workflow.error?.message ??
              "Something went wrong while tailoring. Nothing was charged; failed generations never count against your credits."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {hasResult ? (
              <Button
                size="sm"
                onClick={async () => {
                  try {
                    await api.iterate(id, {});
                    restartPolling();
                  } catch (e) {
                    toast.error(e);
                  }
                }}
              >
                Retry
              </Button>
            ) : (
              <ButtonLink size="sm" href={`/tailor/new${workflow.source_resume_version_id ? `?version=${workflow.source_resume_version_id}` : ""}`}>
                Try again
              </ButtonLink>
            )}
            <ButtonLink size="sm" variant="secondary" href="/dashboard">
              Back to dashboard
            </ButtonLink>
          </div>
        </Alert>
      )}

      {workflow.status === "cancelled" && !hasResult && (
        <Alert tone="info" className="mb-8">
          This tailoring was cancelled.{" "}
          <Link href="/tailor/new" className="underline">
            Start a new one
          </Link>
          .
        </Alert>
      )}

      {latest && (
        <div className="space-y-10">
          <ExportBar generated={latest} onApproved={(g) => setDetail((d) => (d?.latest ? { ...d, latest: { ...d.latest, ...g } } : d))} />
          <div className="grid gap-6 lg:grid-cols-2">
            <ScoresPanel before={detail.scores_before} latest={latest} />
            <SimulationPanel feedback={detail.feedback ?? latest.simulated_feedback ?? null} score={latest.simulation_score} />
          </div>
          <GapsPanel gaps={detail.gaps} />
          <ChangeReview
            workflowId={id}
            generatedId={latest.id}
            changes={detail.changes}
            busy={isActive(workflow.status)}
            onChange={(update) => setDetail((d) => (d ? { ...d, changes: update(d.changes) } : d))}
            onIterationStarted={() => {
              setDetail((d) => (d ? { ...d, workflow: { ...d.workflow, status: "queued" } } : d));
              restartPolling();
            }}
          />
        </div>
      )}
    </>
  );
}
