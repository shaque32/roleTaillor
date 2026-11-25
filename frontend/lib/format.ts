import type { Gap, WorkflowStatus } from "./types";

export function formatDate(iso?: string | null, opts: Intl.DateTimeFormatOptions = { dateStyle: "medium" }): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, opts).format(d);
}

export function formatScore(n?: number | null): string {
  return n === null || n === undefined || Number.isNaN(Number(n)) ? "—" : String(Math.round(Number(n)));
}

export function gapTerm(g: Gap): string {
  return typeof g === "string" ? g : g.term;
}

export const STATUS_LABEL: Record<WorkflowStatus, string> = {
  draft: "Draft",
  queued: "Queued",
  running: "Tailoring",
  paused: "Paused",
  completed: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function isActive(status: WorkflowStatus): boolean {
  return status === "queued" || status === "running";
}

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** ISO string -> value for <input type="date"> */
export function toDateInput(iso?: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}
