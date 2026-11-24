"use client";

import { Download, Eye, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, exportAndOpen } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { gapTerm, isActive } from "@/lib/format";
import type { ExportKind, WorkflowRow } from "@/lib/types";
import { Badge, Button, ButtonLink, ScoreBar, Skeleton, useToast } from "@/components/ui";

export function RowDetail({ row }: { row: WorkflowRow }) {
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
  const pending = changes.filter((c) => c.decision === "pending").length;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
      <div className="space-y-4">
        {latest ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <ScoreBar label="ATS" value={latest.ats_score} before={scores_before?.ats} />
            <ScoreBar label="Job alignment" value={latest.job_alignment_score} before={scores_before?.job_alignment} />
          </div>
        ) : (
          <p className="text-sm text-ink-muted">{isActive(row.status) ? "Tailoring in progress…" : "No generated resume yet."}</p>
        )}
        <p className="text-sm text-ink-muted">
          {changes.length} change{changes.length === 1 ? "" : "s"} proposed{pending ? `, ${pending} awaiting review` : ""}
          {latest?.approved_at ? " · Approved" : ""}
        </p>
        {gaps.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-ink-muted">Gaps:</span>
            {gaps.slice(0, 6).map((g) => (
              <Badge key={gapTerm(g)} tone="amber">
                {gapTerm(g)}
              </Badge>
            ))}
            {gaps.length > 6 && <span className="text-xs text-ink-muted">+{gaps.length - 6} more</span>}
          </div>
        )}
      </div>
      <div className="flex flex-wrap content-start gap-2 lg:w-56 lg:flex-col">
        <ButtonLink href={`/tailor/${row.id}`} size="sm">
          <Eye className="h-4 w-4" aria-hidden /> Open review
        </ButtonLink>
        <Button size="sm" variant="secondary" disabled={!latest} loading={busy === "docx"} onClick={() => download("docx")}>
          <Download className="h-4 w-4" aria-hidden /> DOCX
        </Button>
        <Button size="sm" variant="secondary" disabled={!latest} loading={busy === "pdf"} onClick={() => download("pdf")}>
          <Download className="h-4 w-4" aria-hidden /> PDF
        </Button>
        {row.status === "completed" && (
          <ButtonLink href={`/tailor/${row.id}#iterate`} size="sm" variant="ghost">
            <RefreshCw className="h-4 w-4" aria-hidden /> Iterate
          </ButtonLink>
        )}
      </div>
    </div>
  );
}
