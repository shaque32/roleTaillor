"use client";

import { useMemo } from "react";
import { diffPhrases } from "@/lib/diff";
import { cx } from "@/lib/format";

/**
 * Before/after with phrase-level highlighting. After comes first when stacked (below md, or layout="stacked").
 * When most of the text changed (reordered or rewritten) highlighting is turned off because it would only add noise.
 */
export function DiffView({ before, after, layout = "auto" }: { before: string; after: string; layout?: "auto" | "stacked" }) {
  const { segments, ratio } = useMemo(() => diffPhrases(before, after), [before, after]);
  const plain = ratio > 0.6;
  const stacked = layout === "stacked";
  return (
    <div>
      {plain && <p className="mb-3 text-xs text-ink-muted">Mostly rewritten or reordered</p>}
      <div className={cx("grid gap-4", !stacked && "md:grid-cols-2 md:gap-8")}>
        <div className={cx("min-w-0", stacked ? "order-1" : "order-1 md:order-2")}>
          <p className="mb-1.5 text-xs font-medium text-ink-muted">Suggested rewrite</p>
          <p className="whitespace-pre-wrap text-base leading-relaxed text-ink">
            {plain ? (
              after
            ) : (
              segments.map((s, i) =>
                s.op === "delete" ? null : s.op === "insert" ? (
                  <ins key={i} className="rounded bg-emerald-100 px-0.5 text-emerald-900 no-underline">
                    {s.text}
                  </ins>
                ) : (
                  <span key={i}>{s.text}</span>
                ),
              )
            )}
            {!after && <span className="italic text-ink-muted">(removed)</span>}
          </p>
        </div>
        <div className={cx("min-w-0", stacked ? "order-2 border-l-2 border-line pl-4" : "order-2 border-l-2 border-line pl-4 md:order-1 md:border-l-0 md:pl-0")}>
          <p className="mb-1.5 text-xs font-medium text-ink-muted">Your original</p>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-muted">
            {plain ? (
              before
            ) : (
              segments.map((s, i) =>
                s.op === "insert" ? null : s.op === "delete" ? (
                  <del key={i} className="text-ink-muted decoration-red-400">
                    {s.text}
                  </del>
                ) : (
                  <span key={i}>{s.text}</span>
                ),
              )
            )}
            {!before && <span className="italic">(empty)</span>}
          </p>
        </div>
      </div>
    </div>
  );
}
