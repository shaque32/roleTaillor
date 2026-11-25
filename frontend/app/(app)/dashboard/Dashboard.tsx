"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronDown, FileText, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { cx, formatDate, isActive } from "@/lib/format";
import { getConsentHint } from "@/lib/consent";
import type { WorkflowRow } from "@/lib/types";
import { Alert, Button, ButtonLink, Card, EmptyState, IconButton, PageHeader, ScoreChip, SkeletonRows, StatusBadge, focusRing } from "@/components/ui";
import { BillingMeter } from "@/components/BillingMeter";
import { ConsentDialog } from "@/components/ConsentDialog";
import { RowDetail } from "./RowDetail";

export function Dashboard() {
  const { data, error, loading, setData } = useResource(() => api.workflows());
  const [open, setOpen] = useState<string | null>(null);
  const [declined, setDeclined] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const rows = data ? [...data].sort((a, b) => b.created_at.localeCompare(a.created_at)) : [];
  const toggle = (id: string) => setOpen((cur) => (cur === id ? null : id));
  const anyActive = !!data && data.some((r) => isActive(r.status));

  useEffect(() => {
    setDeclined(getConsentHint() === "declined");
  }, []);

  // Live refresh while something is running. setData (not reload) so the list never flashes a skeleton.
  useEffect(() => {
    if (!anyActive) return;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      api
        .workflows()
        .then(setData)
        .catch(() => undefined);
    };
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, [anyActive, setData]);

  return (
    <>
      <PageHeader title="Tailored resumes" description="One for each job you've gone for. Newest first." actions={<BillingMeter />} />
      {declined && (
        <Alert
          tone="info"
          title="One step left before you can tailor"
          action={
            <Button size="sm" onClick={() => setConsentOpen(true)}>
              Review
            </Button>
          }
        >
          We need your OK to process your resume with AI.
        </Alert>
      )}
      <ConsentDialog open={consentOpen} onClose={() => setConsentOpen(false)} onGranted={() => setDeclined(false)} />
      {loading && !data && <SkeletonRows rows={4} />}
      {error && <Alert tone="error">{error.message}</Alert>}
      {data && rows.length === 0 && (
        <EmptyState
          icon={FileText}
          title="Tailor your first resume"
          description="Add a job, and get a role-specific version with scores and a change-by-change review."
          action={
            <ButtonLink href="/tailor/new">
              <Plus className="h-4 w-4" aria-hidden /> New tailoring
            </ButtonLink>
          }
          secondaryAction={
            <ButtonLink href="/resumes" variant="secondary">
              Add a resume first
            </ButtonLink>
          }
        />
      )}
      {rows.length > 0 && (
        <ul className={cx("space-y-3", declined && "mt-6")}>
          {rows.map((r) => (
            <Row key={r.id} row={r} open={open === r.id} onToggle={() => toggle(r.id)} />
          ))}
        </ul>
      )}
    </>
  );
}

function Row({ row, open, onToggle }: { row: WorkflowRow; open: boolean; onToggle: () => void }) {
  const role = row.target_role ?? "workflow";
  return (
    <li>
      <Card>
        <div className="flex items-start gap-3 p-4 sm:gap-4 sm:p-5">
          <Link href={`/tailor/${row.id}`} className={cx("group min-w-0 flex-1 rounded-lg", focusRing)}>
            <p className="line-clamp-2 break-words text-base font-medium text-ink group-hover:underline">{row.target_role ?? "Untitled role"}</p>
            <p className="mt-0.5 line-clamp-2 break-words text-sm text-ink-muted">
              {row.company ?? "Company not set"} · {row.resume_name ?? "Resume"}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <ScoreChip label="ATS match" value={row.ats_score} />
              <ScoreChip label="Manager sim" value={row.simulation_score} title="Hiring-manager simulation (AI)" />
              <span className="text-xs text-ink-muted">{formatDate(row.created_at)}</span>
            </div>
          </Link>
          <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
            <StatusBadge status={row.status} />
            <IconButton
              size="sm"
              onClick={onToggle}
              aria-expanded={open}
              aria-controls={`detail-${row.id}`}
              label={`${open ? "Hide" : "Show"} details for ${role}`}
            >
              <ChevronDown className={cx("h-5 w-5 transition-transform", open && "rotate-180")} aria-hidden />
            </IconButton>
          </div>
        </div>
        {open && (
          <div id={`detail-${row.id}`} className="border-t border-line p-4 sm:p-5">
            <RowDetail row={row} />
          </div>
        )}
      </Card>
    </li>
  );
}
