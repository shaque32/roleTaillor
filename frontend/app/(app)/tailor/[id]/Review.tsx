"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { isActive } from "@/lib/format";
import type { WorkflowDetail } from "@/lib/types";
import { Alert, Badge, Button, ButtonLink, Dialog, PageHeader, SkeletonRows, StatusBadge, TabPanel, Tabs, useToast } from "@/components/ui";
import { Progress } from "./Progress";
import { SimulationPanel } from "./SimulationPanel";
import { GapsPanel } from "./GapsPanel";
import { ChangeReview } from "./ChangeReview";
import { ResultSummary } from "./ResultSummary";

const POLL_MS = 2000;

export function Review() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [startedAt] = useState(() => Date.now());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pollKey, setPollKey] = useState(0);
  const [tab, setTab] = useState("changes");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const scrolled = useRef(false);

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

  // The dashboard links to #iterate: scroll to the rewrite block once the result is on screen.
  const hasLatest = Boolean(detail?.latest);
  useEffect(() => {
    if (!hasLatest || scrolled.current || window.location.hash !== "#iterate") return;
    scrolled.current = true;
    requestAnimationFrame(() => document.getElementById("iterate")?.scrollIntoView({ block: "start" }));
  }, [hasLatest]);

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

  if (!detail && !error) return <SkeletonRows rows={4} />;
  if (!detail) return <Alert tone="error">{error?.message}</Alert>;

  const { workflow, latest } = detail;
  const role = workflow.target_role ?? "Tailored resume";
  const hasResult = Boolean(latest);
  const active = isActive(workflow.status);

  return (
    <>
      <PageHeader
        back={{ href: "/dashboard", label: "Tailored resumes" }}
        title={workflow.company ? `${role} · ${workflow.company}` : role}
        meta={
          <>
            <StatusBadge status={workflow.status} />
            {latest && <span className="text-sm text-ink-muted">Version {latest.iteration}</span>}
            {latest?.approved_at && <Badge tone="green">Approved</Badge>}
          </>
        }
      />

      {error && (
        <Alert tone="warning" className="mb-6">
          Connection hiccup: {error.message} We&apos;ll keep trying.
        </Alert>
      )}

      {active && (
        <Progress
          status={workflow.status}
          stage={workflow.stage}
          startedAt={startedAt}
          iterating={hasResult}
          compact={hasResult}
          onPause={() => control("pause")}
          onCancel={() => setConfirmCancel(true)}
        />
      )}

      {workflow.status === "paused" && (
        <Alert
          tone="warning"
          title="Paused"
          className="mb-8"
          action={
            <Button size="sm" onClick={() => control("resume")}>
              Resume
            </Button>
          }
        >
          Nothing is running right now. Resume when you&apos;re ready.
        </Alert>
      )}

      {workflow.status === "failed" && (
        <Alert
          tone="error"
          title="This tailoring didn't finish"
          className="mb-8"
          action={
            <div className="flex flex-wrap gap-2">
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
                Back to tailored resumes
              </ButtonLink>
            </div>
          }
        >
          {workflow.recovery_message ??
            workflow.error?.message ??
            "Something went wrong while tailoring. Nothing was charged; failed generations never count against your credits."}
        </Alert>
      )}

      {workflow.status === "cancelled" && !hasResult && (
        <Alert
          tone="info"
          className="mb-8"
          action={
            <ButtonLink size="sm" variant="secondary" href="/tailor/new">
              Start a new one
            </ButtonLink>
          }
        >
          This tailoring was cancelled.
        </Alert>
      )}

      {latest && (
        <div className="space-y-8">
          <ResultSummary
            generated={latest}
            before={detail.scores_before}
            onApproved={(g) => setDetail((d) => (d?.latest && d.latest.id === g.id ? { ...d, latest: { ...d.latest, ...g } } : d))}
          />
          <div>
            <Tabs
              aria-label="Result details"
              value={tab}
              onChange={setTab}
              tabs={[
                {
                  id: "changes",
                  label: "Changes",
                  count: detail.changes.length,
                },
                {
                  id: "gaps",
                  label: "Missing keywords",
                  count: detail.gaps.length,
                },
                { id: "feedback", label: "Hiring-manager view" },
              ]}
            />
            <div className="pt-6">
              <TabPanel id="changes" active={tab === "changes"}>
                <ChangeReview
                  workflowId={id}
                  generatedId={latest.id}
                  changes={detail.changes}
                  busy={active}
                  onChange={(update) => setDetail((d) => (d ? { ...d, changes: update(d.changes) } : d))}
                  onIterationStarted={() => {
                    setDetail((d) =>
                      d
                        ? {
                            ...d,
                            workflow: { ...d.workflow, status: "queued" },
                          }
                        : d,
                    );
                    restartPolling();
                  }}
                />
              </TabPanel>
              <TabPanel id="gaps" active={tab === "gaps"}>
                <GapsPanel gaps={detail.gaps} />
              </TabPanel>
              <TabPanel id="feedback" active={tab === "feedback"}>
                <SimulationPanel feedback={detail.feedback ?? latest.simulated_feedback ?? null} score={latest.simulation_score} />
              </TabPanel>
            </div>
          </div>
        </div>
      )}

      <Dialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        size="sm"
        title="Stop this tailoring?"
        description="Nothing is charged for a cancelled run."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmCancel(false)}>
              Keep going
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirmCancel(false);
                void control("cancel");
              }}
            >
              Stop
            </Button>
          </>
        }
      />
    </>
  );
}
