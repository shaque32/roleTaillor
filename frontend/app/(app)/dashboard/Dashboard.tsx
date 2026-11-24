"use client";

import Link from "next/link";
import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import type { WorkflowRow } from "@/lib/types";
import { Alert, ButtonLink, EmptyState, PageHeader, ScorePill, SkeletonRows, StatusBadge } from "@/components/ui";
import { BillingMeter } from "@/components/BillingMeter";
import { RowDetail } from "./RowDetail";

export function Dashboard() {
  const { data, error, loading } = useResource(() => api.workflows());
  const [open, setOpen] = useState<string | null>(null);
  const rows = data ? [...data].sort((a, b) => b.created_at.localeCompare(a.created_at)) : [];
  const toggle = (id: string) => setOpen((cur) => (cur === id ? null : id));

  return (
    <>
      <PageHeader title="Dashboard" description="Your tailored resumes, newest first." actions={<BillingMeter />} />
      {loading && <SkeletonRows rows={5} />}
      {error && <Alert tone="error">{error.message}</Alert>}
      {data && rows.length === 0 && (
        <EmptyState
          icon={FileText}
          title="Tailor your first resume"
          description="Pick a resume, paste a job, and get an honest, role-specific version with scores and a change review."
          action={
            <ButtonLink href="/tailor/new">
              <Plus className="h-4 w-4" aria-hidden /> New tailoring
            </ButtonLink>
          }
        />
      )}
      {rows.length > 0 && (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-hidden rounded-lg border border-slate-200 bg-white md:block">
            <table className="w-full text-sm">
              <caption className="sr-only">Tailoring workflows</caption>
              <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="w-8 px-3 py-3">
                    <span className="sr-only">Expand</span>
                  </th>
                  <th scope="col" className="px-3 py-3">Resume</th>
                  <th scope="col" className="px-3 py-3">Target role</th>
                  <th scope="col" className="px-3 py-3">Company</th>
                  <th scope="col" className="px-3 py-3 text-right">ATS</th>
                  <th scope="col" className="px-3 py-3 text-right" title="Hiring-manager simulation (AI)">HM sim.</th>
                  <th scope="col" className="px-3 py-3">Date</th>
                  <th scope="col" className="px-3 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr className="hover:bg-slate-50">
                      <td className="px-3 py-3">
                        <button
                          onClick={() => toggle(r.id)}
                          aria-expanded={open === r.id}
                          aria-controls={`detail-${r.id}`}
                          aria-label={`${open === r.id ? "Hide" : "Show"} details for ${r.target_role ?? "workflow"}`}
                          className="rounded p-1 text-ink-faint hover:bg-slate-100 hover:text-ink"
                        >
                          {open === r.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                      </td>
                      <td className="max-w-[14rem] truncate px-3 py-3 font-medium">
                        <Link href={`/tailor/${r.id}`} className="hover:underline">
                          {r.resume_name ?? "Resume"}
                        </Link>
                      </td>
                      <td className="max-w-[14rem] truncate px-3 py-3">{r.target_role ?? "—"}</td>
                      <td className="max-w-[10rem] truncate px-3 py-3 text-ink-muted">{r.company ?? "—"}</td>
                      <td className="px-3 py-3 text-right">
                        <ScorePill value={r.ats_score} />
                      </td>
                      <td className="px-3 py-3 text-right">
                        <ScorePill value={r.simulation_score} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-ink-muted">{formatDate(r.created_at)}</td>
                      <td className="px-3 py-3">
                        <StatusBadge status={r.status} />
                      </td>
                    </tr>
                    {open === r.id && (
                      <tr id={`detail-${r.id}`}>
                        <td colSpan={8} className="bg-slate-50/60 px-6 py-5">
                          <RowDetail row={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile list */}
          <ul className="space-y-3 md:hidden">
            {rows.map((r) => (
              <MobileRow key={r.id} row={r} open={open === r.id} onToggle={() => toggle(r.id)} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function MobileRow({ row, open, onToggle }: { row: WorkflowRow; open: boolean; onToggle: () => void }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-start justify-between gap-3 p-4 text-left">
        <div className="min-w-0">
          <p className="truncate font-medium">{row.target_role ?? "Untitled role"}</p>
          <p className="truncate text-sm text-ink-muted">
            {row.company ?? "—"} · {row.resume_name ?? "Resume"}
          </p>
          <p className="mt-2 flex gap-4 text-xs text-ink-muted">
            <span>
              ATS <ScorePill value={row.ats_score} />
            </span>
            <span>
              HM sim. <ScorePill value={row.simulation_score} />
            </span>
            <span>{formatDate(row.created_at)}</span>
          </p>
        </div>
        <StatusBadge status={row.status} />
      </button>
      {open && (
        <div className="border-t border-slate-100 p-4">
          <RowDetail row={row} />
        </div>
      )}
    </li>
  );
}

