"use client";

import { useRef } from "react";
import { cx } from "@/lib/format";
import { Badge } from "./Badge";
import { focusRing } from "./styles";

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

/** WAI-ARIA tabs with automatic activation. Pair with <TabPanel>. */
export function Tabs({
  tabs,
  value,
  onChange,
  "aria-label": ariaLabel,
  className,
}: {
  tabs: TabItem[];
  value: string;
  onChange: (id: string) => void;
  "aria-label": string;
  className?: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function move(to: number) {
    const t = tabs[(to + tabs.length) % tabs.length];
    if (!t) return;
    onChange(t.id);
    refs.current[t.id]?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent, i: number) {
    if (e.key === "ArrowRight") move(i + 1);
    else if (e.key === "ArrowLeft") move(i - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(tabs.length - 1);
    else return;
    e.preventDefault();
  }

  return (
    <div className={cx("overflow-x-auto border-b border-line", className)}>
      <div role="tablist" aria-label={ariaLabel} className="flex min-w-max gap-1">
        {tabs.map((t, i) => {
          const selected = t.id === value;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[t.id] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={selected}
              aria-controls={`panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={cx(
                "-mb-px inline-flex h-11 items-center gap-2 rounded-t-lg border-b-2 px-4 text-sm transition-colors",
                selected ? "border-brand-600 font-medium text-ink" : "border-transparent text-ink-muted hover:text-ink",
                focusRing,
              )}
            >
              {t.label}
              {t.count !== undefined && <Badge tone={selected ? "brand" : "neutral"}>{t.count}</Badge>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function TabPanel({ id, active, children, className }: { id: string; active: boolean; children: React.ReactNode; className?: string }) {
  // Inactive panels stay mounted (so their state survives tab switches) but hidden from view and the a11y tree.
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} hidden={!active} tabIndex={active ? 0 : -1} className={cx("rounded-lg", focusRing, className)}>
      {children}
    </div>
  );
}
