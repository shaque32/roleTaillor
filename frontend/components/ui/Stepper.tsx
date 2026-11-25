import { Check } from "lucide-react";
import { cx } from "@/lib/format";
import { Spinner } from "./Spinner";

export interface StepItem {
  id: string;
  label: string;
  description?: string;
}

export function Stepper({
  steps,
  current,
  orientation = "horizontal",
  "aria-label": ariaLabel,
  showLabelsOnMobile = false,
  activeLabel,
  className,
}: {
  steps: StepItem[];
  current: number;
  orientation?: "horizontal" | "vertical";
  "aria-label": string;
  showLabelsOnMobile?: boolean;
  activeLabel?: React.ReactNode;
  className?: string;
}) {
  const vertical = orientation === "vertical";

  const marker = (i: number) => {
    const done = i < current;
    const active = i === current;
    return (
      <span
        aria-hidden
        className={cx(
          "grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold",
          done && "bg-brand-600 text-white",
          active && "bg-white text-brand-700 ring-2 ring-brand-600",
          !done && !active && "bg-surface-sunken text-ink-muted",
        )}
      >
        {done ? <Check className="h-4 w-4" strokeWidth={3} /> : active && vertical ? <Spinner className="h-3.5 w-3.5" /> : i + 1}
      </span>
    );
  };

  const text = (s: StepItem, i: number) => {
    const state = i < current ? "Completed: " : i === current ? "Current: " : "Not started: ";
    return (
      <span className={cx("min-w-0", !vertical && !showLabelsOnMobile && "max-sm:sr-only")}>
        <span className="sr-only">{state}</span>
        <span className={cx("block text-sm", i === current ? "font-medium text-ink" : i < current ? "text-ink" : "text-ink-muted")}>
          {i === current && activeLabel ? activeLabel : s.label}
        </span>
        {s.description && <span className="block text-xs text-ink-muted">{s.description}</span>}
      </span>
    );
  };

  if (vertical) {
    return (
      <ol aria-label={ariaLabel} className={className}>
        {steps.map((s, i) => (
          <li key={s.id} aria-current={i === current ? "step" : undefined} className="flex gap-3">
            <div className="flex flex-col items-center">
              {marker(i)}
              {i < steps.length - 1 && <span aria-hidden className={cx("my-1 w-0.5 flex-1 min-h-4", i < current ? "bg-brand-600" : "bg-line")} />}
            </div>
            <div className={cx("pt-1", i < steps.length - 1 && "pb-3")}>{text(s, i)}</div>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <div className={className}>
      <ol aria-label={ariaLabel} className="flex items-center gap-3">
        {steps.map((s, i) => (
          <li key={s.id} aria-current={i === current ? "step" : undefined} className={cx("flex items-center gap-3", i < steps.length - 1 && "flex-1")}>
            {marker(i)}
            {text(s, i)}
            {i < steps.length - 1 && <span aria-hidden className={cx("h-0.5 min-w-4 flex-1 rounded-full", i < current ? "bg-brand-600" : "bg-line")} />}
          </li>
        ))}
      </ol>
      {!showLabelsOnMobile && current < steps.length && (
        <p className="mt-3 text-sm text-ink-muted sm:hidden" aria-hidden>
          Step {current + 1} of {steps.length} · {steps[current]!.label}
        </p>
      )}
    </div>
  );
}
