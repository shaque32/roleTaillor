"use client";

import { useId, useState } from "react";
import { cx } from "@/lib/format";

export interface SegmentOption<V extends string = string> {
  value: V;
  label: string;
  count?: number;
  disabled?: boolean;
}
export interface SegmentedControlProps<V extends string = string> {
  options: SegmentOption<V>[];
  /** Controlled when present (not undefined). null = controlled with nothing selected. */
  value?: V | null;
  defaultValue?: V;
  onChange?: (value: V) => void;
  name?: string;
  label?: string;
  "aria-label"?: string;
  variant?: "track" | "chips";
  size?: "sm" | "md";
  fullWidth?: boolean;
  className?: string;
}

const focus = "peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500 peer-focus-visible:ring-offset-2 peer-focus-visible:relative peer-focus-visible:z-10";

/** Short, mutually exclusive options (and filter chips). Native radios: arrow keys, one tab stop and FormData for free. */
export function SegmentedControl<V extends string = string>({
  options,
  value,
  defaultValue,
  onChange,
  name,
  label,
  "aria-label": ariaLabel,
  variant = "track",
  size = "md",
  fullWidth,
  className,
}: SegmentedControlProps<V>) {
  const auto = useId();
  const group = name ?? auto;
  const labelId = `${auto}-label`;
  const [inner, setInner] = useState<V | undefined>(defaultValue);
  const current = value !== undefined ? value : inner;
  const chips = variant === "chips";
  const h = size === "sm" ? "h-9" : "h-11";

  const items = options.map((o) => (
    <label key={o.value} className={cx("relative cursor-pointer", !chips && fullWidth && "flex-1", o.disabled && "cursor-not-allowed")}>
      <input
        type="radio"
        className="peer sr-only"
        name={group}
        value={o.value}
        checked={current === o.value}
        disabled={o.disabled}
        onChange={() => {
          if (value === undefined) setInner(o.value);
          onChange?.(o.value);
        }}
      />
      <span
        className={cx(
          "inline-flex items-center justify-center gap-1.5 whitespace-nowrap text-sm transition-colors peer-disabled:opacity-50",
          h,
          focus,
          chips
            ? "rounded-full px-3.5 bg-white ring-1 ring-line text-ink-muted hover:text-ink peer-checked:bg-brand-600 peer-checked:text-white peer-checked:ring-brand-600 peer-checked:hover:text-white"
            : "w-full rounded-md px-3.5 text-ink-muted hover:text-ink peer-checked:bg-white peer-checked:font-medium peer-checked:text-ink peer-checked:shadow-sm",
        )}
      >
        {o.label}
        {o.count !== undefined && <span className="tabular-nums opacity-70">{o.count}</span>}
      </span>
    </label>
  ));

  return (
    <div className={className}>
      {label && (
        <p id={labelId} className="mb-2 text-sm font-medium text-ink">
          {label}
        </p>
      )}
      <div
        role="radiogroup"
        aria-labelledby={label ? labelId : undefined}
        aria-label={label ? undefined : ariaLabel}
        className={cx(chips ? "flex flex-wrap gap-2" : cx("rounded-lg bg-surface-sunken p-0.5", fullWidth ? "flex w-full" : "inline-flex max-w-full overflow-x-auto"))}
      >
        {items}
      </div>
    </div>
  );
}
