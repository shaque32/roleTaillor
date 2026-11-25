"use client";

import { Download, Eye, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, exportAndOpen } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { gapTerm, isActive } from "@/lib/format";
import type { ExportKind, WorkflowRow } from "@/lib/types";
import { Badge, Button, ButtonLink, ScoreBar, Skeleton, Spinner, useToast } from "@/components/ui";

export function RowDetail({ row }: { row: WorkflowRow }) {
  const running = isActive(row.status);
  // A running row without a result needs no detail request at all.
  if (running && row.ats_score == null) return <Running id={row.id} />;
  return <Loaded row={row} />;
}

function Running({ id }: { id: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <p className="flex items-center gap-2 text-sm text-ink-muted">
        <Spinner className="h-4 w-4" /> Tailoring in progress. Usually under a minute.
      </p>
      <ButtonLink href={`/tailor/${id}`} size="sm">
        View progress
      </ButtonLink>
    </div>
  );
}

function Loaded({ row }: { row: WorkflowRow }) {
  const toast = useToast();
  const { data, loading, error } = useResource(() => api.workflow(row.id), [row.id]);
  const [busy, setBusy] = useState<ExportKind | null>(null);

  async function download(kind: ExportKind) {
    if (!data?.latest) return;
    setBusy(kind);
    try {
      await exportAndOpen(data.latest.id, kind);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Skeleton className="h-24 w-full" />;
  if (error || !data) return <p className="text-sm text-red-700">{error?.message ?? "Couldn't load details."}</p>;

  const { latest, scores_before, gaps, changes } = data;

  if (!latest) {
    if (isActive(row.status)) return <Running id={row.id} />;
    if (row.status === "failed") {
      return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="text-sm text-ink-muted">This one didn&apos;t finish. Nothing was charged.</p>
          <ButtonLink href={`/tailor/${row.id}`} size="sm" variant="secondary">
            See what happened
          </ButtonLink>
        </div>
      );
    }
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm text-ink-muted">No result yet.</p>
        <ButtonLink href={`/tailor/${row.id}`} size="sm" variant="secondary">
          Open
        </ButtonLink>
      </div>
    );
  }

  const pending = changes.filter((c) => c.decision === "pending").length;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <ScoreBar label="ATS match" value={latest.ats_score} before={scores_before?.ats} />
        <ScoreBar label="Job alignment" value={latest.job_alignment_score} before={scores_before?.job_alignment} />
      </div>
      <p className="text-sm text-ink-muted">
        {changes.length} rewrite{changes.length === 1 ? "" : "s"}
        {pending ? `, ${pending} still to review` : ""}
        {latest.approved_at ? " · Marked as final" : ""}
      </p>
      {gaps.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-muted">Missing keywords:</span>
          {gaps.slice(0, 6).map((g) => (
            <Badge key={gapTerm(g)} tone="amber">
              {gapTerm(g)}
            </Badge>
          ))}
          {gaps.length > 6 && <span className="text-xs text-ink-muted">+{gaps.length - 6} more</span>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <ButtonLink href={`/tailor/${row.id}`} size="sm">
          <Eye className="h-4 w-4" aria-hidden /> Open review
        </ButtonLink>
        <Button size="sm" variant="secondary" loading={busy === "docx"} onClick={() => download("docx")}>
          <Download className="h-4 w-4" aria-hidden /> Word
        </Button>
        <Button size="sm" variant="secondary" loading={busy === "pdf"} onClick={() => download("pdf")}>
          <Download className="h-4 w-4" aria-hidden /> PDF
        </Button>
        {row.status === "completed" && (
          <ButtonLink href={`/tailor/${row.id}#iterate`} size="sm" variant="ghost">
            <RefreshCw className="h-4 w-4" aria-hidden /> Ask for changes
          </ButtonLink>
        )}
      </div>
    </div>
  );
}
