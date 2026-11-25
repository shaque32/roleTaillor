import { cx } from "@/lib/format";
import { STATUS_LABEL } from "@/lib/format";
import type { WorkflowStatus } from "@/lib/types";

type Tone = "neutral" | "blue" | "brand" | "green" | "amber" | "red";
const tones: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700",
  blue: "bg-brand-50 text-brand-700",
  brand: "bg-brand-50 text-brand-700",
  green: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-800",
  red: "bg-red-50 text-red-700",
};

export function Badge({ tone = "neutral", className, children, dot, dotClassName }: { tone?: Tone; className?: string; children: React.ReactNode; dot?: boolean; dotClassName?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", tones[tone], className)}>
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full bg-current", dotClassName)} aria-hidden />}
      {children}
    </span>
  );
}

const statusTone: Record<WorkflowStatus, Tone> = {
  draft: "neutral",
  queued: "blue",
  running: "blue",
  paused: "amber",
  completed: "green",
  failed: "red",
  cancelled: "neutral",
};

export function StatusBadge({ status }: { status: WorkflowStatus }) {
  return (
    <Badge tone={statusTone[status] ?? "neutral"} dot dotClassName={status === "queued" || status === "running" ? "animate-pulse" : undefined}>
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}
