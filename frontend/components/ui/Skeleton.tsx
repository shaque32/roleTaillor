import { cx } from "@/lib/format";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cx("animate-shimmer rounded-lg bg-[linear-gradient(90deg,#eef1f6_25%,#f8f9fc_50%,#eef1f6_75%)] bg-[length:200%_100%]", className ?? "h-4 w-full")}
      aria-hidden
    />
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  );
}
