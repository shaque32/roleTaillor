"use client";

import { forwardRef, useEffect, useState } from "react";
import { FileText, ScanLine } from "lucide-react";
import { Alert, Badge, Button, Spinner } from "@/components/ui";
import { readingCopy } from "@/lib/processing";
import { cx } from "@/lib/format";

/** Indeterminate bar: no percentage, because we don't know how far along the reading is. */
export function IndeterminateBar({ className }: { className?: string }) {
  return (
    <div className={cx("h-1.5 overflow-hidden rounded-full bg-surface-sunken", className)} aria-hidden>
      <div className="h-full w-full animate-shimmer bg-[linear-gradient(90deg,#bfd0fd_0%,#3b63d9_50%,#bfd0fd_100%)] bg-[length:200%_100%]" />
    </div>
  );
}

/** Whole seconds since `startedAt`, re-rendered once a second. */
export function useElapsed(startedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  return Math.max(0, now - startedAt);
}

/**
 * Shown in place of the dropzone while a scanned PDF is read in the background.
 * The heading takes focus when it appears (pass the ref) so keyboard users are not left on a removed button.
 */
export const ReadingScan = forwardRef<
  HTMLHeadingElement,
  { fileName?: string; startedAt: number; leaveHint?: React.ReactNode; className?: string }
>(function ReadingScan({ fileName, startedAt, leaveHint, className }, ref) {
  const elapsed = useElapsed(startedAt);
  const copy = readingCopy(elapsed);
  return (
    <div className={cx("rounded-lg border border-line bg-white px-5 py-8 text-center sm:px-8", className)}>
      <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-brand-50 text-brand-600" aria-hidden>
        <ScanLine className="h-6 w-6" />
      </div>
      <h2 ref={ref} tabIndex={-1} className="mt-4 text-lg font-semibold text-ink focus:outline-none">
        {copy.title}
      </h2>
      {fileName && (
        <p className="mt-1 flex items-center justify-center gap-1.5 text-sm text-ink-muted">
          <FileText className="h-4 w-4 shrink-0" aria-hidden />
          <span className="min-w-0 break-all">{fileName}</span>
        </p>
      )}
      <p className="mx-auto mt-3 max-w-md text-sm text-ink-muted" role="status" aria-live="polite">
        {copy.detail}
      </p>
      <IndeterminateBar className="mx-auto mt-5 max-w-xs" />
      {leaveHint && <p className="mx-auto mt-5 max-w-md text-sm text-ink-muted">{leaveHint}</p>}
    </div>
  );
});

/** Failed read: the server's message plus the ways forward. */
export function UnreadableScan({
  message,
  problem,
  onRetry,
  retrying,
  children,
}: {
  message: string;
  problem?: string | null;
  onRetry: () => void;
  retrying?: boolean;
  /** Extra actions after "Try again". */
  children?: React.ReactNode;
}) {
  return (
    <div className="space-y-4">
      <Alert tone="error" title="We couldn't read your scan">
        {message}
      </Alert>
      {problem && <Alert tone="error">{problem}</Alert>}
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button onClick={onRetry} loading={retrying}>
          Try again
        </Button>
        {children}
      </div>
    </div>
  );
}

/** Small list badges. */
export function ReadingBadge() {
  return (
    <Badge tone="brand">
      <Spinner className="h-3 w-3" />
      Reading scan…
    </Badge>
  );
}

export function UnreadableBadge() {
  return <Badge tone="red">Could not read</Badge>;
}
