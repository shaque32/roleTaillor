import { cx } from "@/lib/format";

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <svg className={cx("animate-spin text-current", className ?? "h-5 w-5")} viewBox="0 0 24 24" fill="none" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}
