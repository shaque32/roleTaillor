import type { ResumeDetail, ResumeProcessing, ResumeVersionSummary } from "./types";

/** Poll every 2 s at first, then every 5 s once a scan has been running for a while. */
export const POLL_FAST_MS = 2000;
export const POLL_SLOW_MS = 5000;
export const POLL_BACKOFF_AFTER_MS = 30_000;
/** After this long we tell the person that a long scan is still fine. */
export const STILL_WORKING_AFTER_MS = 45_000;

export function pollDelay(elapsedMs: number): number {
  return elapsedMs >= POLL_BACKOFF_AFTER_MS ? POLL_SLOW_MS : POLL_FAST_MS;
}

export function isReading(r: { processing: ResumeProcessing | null }): boolean {
  return r.processing?.status === "processing";
}

export function isUnreadable(r: { processing: ResumeProcessing | null }): boolean {
  return r.processing?.status === "failed";
}

/** True while the resume has no usable version (reading or failed). Such resumes cannot be tailored or opened as a version. */
export function isUnavailable(r: { processing: ResumeProcessing | null }): boolean {
  return r.processing != null;
}

export const FALLBACK_ERROR = "We couldn't read this scanned PDF. Try a clearer scan, a DOCX, or paste the text instead.";

const FALLBACKS: Record<string, string> = {
  ocr_no_text: "We couldn't find any text in this scan. Try a clearer copy, a DOCX, or paste the text instead.",
  ocr_timeout: "Reading this scan took too long. Try again, or paste the text instead.",
  ocr_failed: FALLBACK_ERROR,
  ocr_unavailable: "Reading scanned PDFs is unavailable right now. Please try again in a few minutes.",
};

/** The server writes `error.message` for end users, so show it; fall back to a per-code string. */
export function processingMessage(p: ResumeProcessing | null | undefined): string {
  const msg = p?.error?.message?.trim();
  if (msg) return msg;
  return (p?.error?.code && FALLBACKS[p.error.code]) || FALLBACK_ERROR;
}

/** Copy for the reading state, depending on how long it has been going. */
export function readingCopy(elapsedMs: number): { title: string; detail: string } {
  if (elapsedMs >= STILL_WORKING_AFTER_MS) {
    return { title: "Still reading your scan…", detail: "Still working. Longer scans take a bit more time." };
  }
  return { title: "Reading your scan…", detail: "This PDF is a scan, so we're reading the text from its pages. It usually takes under a minute." };
}

/** Newest version of a resume detail, or null while there is none. */
export function latestVersionOf(detail: Pick<ResumeDetail, "versions">): ResumeVersionSummary | null {
  let best: ResumeVersionSummary | null = null;
  for (const v of detail.versions) if (!best || v.version_number > best.version_number) best = v;
  return best;
}

/** Parse the server's started_at; fall back to `fallback` when missing, invalid or implausibly in the future (clock skew). */
export function startedAtMs(p: ResumeProcessing | null | undefined, fallback = Date.now()): number {
  const t = p?.started_at ? Date.parse(p.started_at) : NaN;
  if (!Number.isFinite(t)) return fallback;
  return Math.min(t, fallback);
}
