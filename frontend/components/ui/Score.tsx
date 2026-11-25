import { cx, formatScore } from "@/lib/format";
import { Badge } from "./Badge";

function tone(n: number) {
  if (n >= 75) return "bg-emerald-500";
  if (n >= 50) return "bg-brand-500";
  return "bg-amber-500";
}

/** Simple horizontal score bar with optional before value shown as a tick. */
export function ScoreBar({ label, value, before }: { label: string; value: number | null | undefined; before?: number | null }) {
  const v = value === null || value === undefined ? null : Math.max(0, Math.min(100, Number(value)));
  const b = before === null || before === undefined ? null : Math.max(0, Math.min(100, Number(before)));
  const delta = v !== null && b !== null ? Math.round(v) - Math.round(b) : null;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-ink-muted">{label}</span>
        <span className="flex items-baseline gap-2 tabular-nums">
          {b !== null && (
            <span className="text-ink-muted">
              <span className="sr-only">before </span>
              {formatScore(b)} →
            </span>
          )}
          <span className="font-semibold text-ink">
            <span className="sr-only">{b !== null ? "after " : ""}</span>
            {formatScore(v)}
          </span>
          {delta !== null && delta !== 0 && (
            <Badge tone={delta > 0 ? "green" : "red"} className="!py-0.5">
              {delta > 0 ? "+" : ""}
              {delta}
            </Badge>
          )}
        </span>
      </div>
      <div
        className="relative mt-2 h-2.5 rounded-full bg-surface-sunken"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={v ?? undefined}
      >
        {v !== null && <div className={cx("h-2.5 rounded-full", tone(v))} style={{ width: `${v}%` }} />}
        {b !== null && (
          <div
            className="absolute top-1/2 h-4 w-0.5 -translate-y-1/2 bg-ink"
            style={{ left: `calc(${b}% - 1px)` }}
            title={`Before: ${formatScore(b)}`}
            aria-hidden
          />
        )}
      </div>
    </div>
  );
}

/** Compact numeric score pill for tables. */
export function ScorePill({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-ink-muted">—</span>;
  const n = Number(value);
  const color = n >= 75 ? "text-emerald-700" : n >= 50 ? "text-ink" : "text-amber-700";
  return <span className={cx("font-semibold tabular-nums", color)}>{formatScore(n)}</span>;
}

/** Ring for headline score. */
export function ScoreRing({ value, label, size = 88 }: { value: number | null | undefined; label: string; size?: number }) {
  const v = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, Number(value)));
  const r = (size - 10) / 2;
  const c = 2 * Math.PI * r;
  const stroke = v >= 75 ? "#10b981" : v >= 50 ? "#3b63d9" : "#f59e0b";
  return (
    <div className="flex flex-col items-center gap-1" role="img" aria-label={`${label}: ${formatScore(value)} out of 100`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#e5e9f0" strokeWidth="10" fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={stroke}
          strokeWidth="10"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${(v / 100) * c} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" className="fill-ink text-xl font-semibold">
          {formatScore(value)}
        </text>
      </svg>
      <span className="text-xs text-ink-muted">{label}</span>
    </div>
  );
}

/** Small labelled score for list rows: "ATS match 82". Renders nothing without a value. */
export function ScoreChip({ label, value, title }: { label: string; value: number | null | undefined; title?: string }) {
  if (value === null || value === undefined) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-sunken px-2.5 py-1 text-xs text-ink-muted" title={title}>
      {label} <ScorePill value={value} />
    </span>
  );
}
