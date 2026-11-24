"use client";

import { useMemo } from "react";
import { diffWords } from "@/lib/diff";

/** Before/after with word-level highlighting. Stacked on mobile, side by side on wide screens. */
export function DiffView({ before, after }: { before: string; after: string }) {
  const segs = useMemo(() => diffWords(before, after), [before, after]);
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-faint">Before</p>
        <p className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm leading-relaxed text-ink-muted">
          {segs.map((s, i) =>
            s.op === "insert" ? null : s.op === "delete" ? (
              <del key={i} className="rounded-sm bg-red-100 text-red-800 decoration-red-400">
                {s.text}
              </del>
            ) : (
              <span key={i}>{s.text}</span>
            ),
          )}
          {!before && <span className="italic text-ink-faint">(empty)</span>}
        </p>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-faint">After</p>
        <p className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm leading-relaxed text-ink">
          {segs.map((s, i) =>
            s.op === "delete" ? null : s.op === "insert" ? (
              <ins key={i} className="rounded-sm bg-emerald-100 text-emerald-900 no-underline">
                {s.text}
              </ins>
            ) : (
              <span key={i}>{s.text}</span>
            ),
          )}
          {!after && <span className="italic text-ink-faint">(removed)</span>}
        </p>
      </div>
    </div>
  );
}
