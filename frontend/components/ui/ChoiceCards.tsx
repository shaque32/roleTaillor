"use client";

import { useId, useState } from "react";
import { Check } from "lucide-react";
import { cx } from "@/lib/format";
import { Badge } from "./Badge";

export interface ChoiceOption<V extends string = string> {
  value: V;
  label: string;
  description?: string;
  icon?: React.ReactNode;
  badge?: string;
  disabled?: boolean;
}
export interface ChoiceCardsProps<V extends string = string> {
  options: ChoiceOption<V>[];
  value?: V;
  defaultValue?: V;
  onChange?: (value: V) => void;
  name?: string;
  label?: string;
  "aria-label"?: string;
  hint?: string;
  columns?: 1 | 2 | 3 | 4;
  className?: string;
}

const cols = { 1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4" };

/** 2 to 4 options that deserve a sentence of explanation. Native radios, so keyboard and forms work for free. */
export function ChoiceCards<V extends string = string>({
  options,
  value,
  defaultValue,
  onChange,
  name,
  label,
  "aria-label": ariaLabel,
  hint,
  columns = 2,
  className,
}: ChoiceCardsProps<V>) {
  const auto = useId();
  const group = name ?? auto;
  const labelId = `${auto}-label`;
  const hintId = `${auto}-hint`;
  const [inner, setInner] = useState<V | undefined>(defaultValue);
  const current = value !== undefined ? value : inner;

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
        aria-describedby={hint ? hintId : undefined}
        className={cx("grid grid-cols-1 gap-3", cols[columns])}
      >
        {options.map((o) => (
          <label key={o.value} className={cx("relative block", o.disabled ? "cursor-not-allowed" : "cursor-pointer")}>
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
                "flex h-full gap-3 rounded-xl bg-white p-4 pr-11 ring-1 ring-line transition hover:ring-ink-faint",
                "peer-checked:bg-brand-50/60 peer-checked:ring-2 peer-checked:ring-brand-500 peer-checked:hover:ring-brand-500",
                "peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500 peer-focus-visible:ring-offset-2 peer-disabled:opacity-50",
              )}
            >
              {o.icon && <span className="mt-0.5 shrink-0 text-brand-600 [&>svg]:h-5 [&>svg]:w-5">{o.icon}</span>}
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{o.label}</span>
                  {o.badge && <Badge tone="brand">{o.badge}</Badge>}
                </span>
                {o.description && <span className="mt-0.5 block text-sm text-ink-muted">{o.description}</span>}
              </span>
            </span>
            <span
              aria-hidden
              className="pointer-events-none absolute right-3.5 top-4 h-5 w-5 rounded-full ring-1 ring-line-field peer-checked:bg-brand-600 peer-checked:ring-0"
            />
            <Check aria-hidden className="pointer-events-none absolute right-3.5 top-4 h-5 w-5 p-1 text-white opacity-0 peer-checked:opacity-100" strokeWidth={3} />
          </label>
        ))}
      </div>
      {hint && (
        <p id={hintId} className="mt-2 text-sm text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
