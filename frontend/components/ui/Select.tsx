"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cx } from "@/lib/format";
import { FieldShell, describedBy } from "./Field";
import { fieldControl, focusRing } from "./styles";

type Tone = "neutral" | "blue" | "green" | "amber" | "red";

export interface SelectOption<V extends string = string> {
  value: V;
  label: string;
  description?: string;
  tone?: Tone;
  disabled?: boolean;
}
export interface SelectProps<V extends string = string> {
  options: SelectOption<V>[];
  value?: V;
  defaultValue?: V;
  onChange?: (value: V) => void;
  name?: string;
  label?: string;
  "aria-label"?: string;
  hint?: string;
  error?: string;
  placeholder?: string;
  disabled?: boolean;
  size?: "sm" | "md";
  variant?: "field" | "pill";
  className?: string;
  id?: string;
}

const dot: Record<Tone, string> = {
  neutral: "bg-slate-400",
  blue: "bg-brand-500",
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-red-500",
};
const pill: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 hover:bg-slate-200",
  blue: "bg-brand-50 text-brand-700 hover:bg-brand-100",
  green: "bg-emerald-50 text-emerald-700 hover:bg-emerald-100",
  amber: "bg-amber-50 text-amber-800 hover:bg-amber-100",
  red: "bg-red-50 text-red-700 hover:bg-red-100",
};

/** Accessible replacement for the native <select> (WAI-ARIA "select-only combobox"). */
export function Select<V extends string = string>(props: SelectProps<V>): ReactElement {
  return <Listbox {...props} />;
}

function Listbox<V extends string>({
  options,
  value: valueProp,
  defaultValue,
  onChange,
  name,
  label,
  "aria-label": ariaLabel,
  hint,
  error,
  placeholder = "Select…",
  disabled,
  size = "md",
  variant = "field",
  className,
  id: idProp,
}: SelectProps<V>) {
  const auto = useId();
  const id = idProp ?? auto;
  const labelId = `${id}-label`;
  const valueId = `${id}-value`;
  const listId = `${id}-list`;
  const optId = (i: number) => `${id}-opt-${i}`;

  const controlled = valueProp !== undefined;
  const [inner, setInner] = useState<V | undefined>(defaultValue);
  const current = controlled ? valueProp : inner;
  const selectedIndex = options.findIndex((o) => o.value === current);
  const selected = selectedIndex >= 0 ? options[selectedIndex]! : undefined;

  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number; width: number }>({ left: 0, width: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: "", timer: 0 as unknown as ReturnType<typeof setTimeout> });

  const enabled = useMemo(() => options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0), [options]);
  const firstEnabled = enabled[0] ?? -1;
  const lastEnabled = enabled[enabled.length - 1] ?? -1;

  const place = useCallback(() => {
    const r = triggerRef.current?.getBoundingClientRect();
    if (!r) return;
    const width = variant === "pill" ? Math.max(r.width, 224) : r.width;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
    const below = window.innerHeight - r.bottom;
    if (below < 300 && r.top > below) setPos({ bottom: window.innerHeight - r.top + 4, left, width });
    else setPos({ top: r.bottom + 4, left, width });
  }, [variant]);

  const openAt = useCallback(
    (index: number) => {
      if (disabled) return;
      place();
      setActive(index);
      setOpen(true);
    },
    [disabled, place],
  );
  const close = useCallback(() => setOpen(false), []);

  const choose = useCallback(
    (i: number) => {
      const o = options[i];
      if (!o || o.disabled) return;
      if (!controlled) setInner(o.value);
      if (o.value !== current) onChange?.(o.value);
      setOpen(false);
    },
    [options, controlled, current, onChange],
  );

  // Outside pointer, scroll and resize close the popup.
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!triggerRef.current?.contains(t) && !listRef.current?.contains(t)) setOpen(false);
    };
    const scroll = (e: Event) => {
      if (!listRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const resize = () => setOpen(false);
    document.addEventListener("pointerdown", down);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", down);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", resize);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (open && active >= 0) document.getElementById(optId(active))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, active]);

  useEffect(() => () => clearTimeout(typed.current.timer), []);

  function typeahead(ch: string, base: number): number {
    clearTimeout(typed.current.timer);
    typed.current.text += ch.toLowerCase();
    typed.current.timer = setTimeout(() => (typed.current.text = ""), 500);
    const text = typed.current.text;
    // Repeating one letter cycles through the options starting with it.
    const same = [...text].every((c) => c === text[0]);
    const needle = same ? text[0]! : text;
    const from = same ? base + 1 : Math.max(base, 0);
    const ordered = [...enabled.filter((i) => i >= from), ...enabled.filter((i) => i < from)];
    return ordered.find((i) => options[i]!.label.toLowerCase().startsWith(needle)) ?? -1;
  }

  function step(from: number, dir: 1 | -1): number {
    const idx = enabled.indexOf(from);
    if (idx < 0) return dir === 1 ? firstEnabled : lastEnabled;
    return enabled[Math.max(0, Math.min(enabled.length - 1, idx + dir))] ?? from;
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    const printable = e.key.length === 1 && e.key !== " " && !e.ctrlKey && !e.metaKey && !e.altKey;
    if (!open) {
      const start = selectedIndex >= 0 && !options[selectedIndex]!.disabled ? selectedIndex : firstEnabled;
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        openAt(start);
      } else if (e.key === "Home") {
        e.preventDefault();
        openAt(firstEnabled);
      } else if (e.key === "End") {
        e.preventDefault();
        openAt(lastEnabled);
      } else if (printable) {
        e.preventDefault();
        const hit = typeahead(e.key, selectedIndex);
        openAt(hit >= 0 ? hit : start);
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActive((a) => step(a, 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActive((a) => step(a, -1));
        break;
      case "Home":
        e.preventDefault();
        setActive(firstEnabled);
        break;
      case "End":
        e.preventDefault();
        setActive(lastEnabled);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        choose(active);
        break;
      case "Tab":
        if (active >= 0) choose(active);
        else close();
        break;
      case "Escape":
        e.preventDefault();
        e.stopPropagation();
        close();
        break;
      default:
        if (printable) {
          e.preventDefault();
          const hit = typeahead(e.key, active);
          if (hit >= 0) setActive(hit);
        }
    }
  }

  const isPill = variant === "pill";
  const triggerClass = isPill
    ? cx("inline-flex h-9 max-w-full items-center gap-2 rounded-full px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60", pill[selected?.tone ?? "neutral"], focusRing)
    : cx(fieldControl.replace(/^block /, ""), "flex items-center justify-between gap-2 text-left", size === "sm" ? "h-9 px-3 text-sm" : "h-12 text-base");

  const body = (
    <div className={cx("relative", isPill ? "inline-block max-w-full" : undefined)}>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && active >= 0 ? optId(active) : undefined}
        aria-labelledby={label ? `${labelId} ${valueId}` : `${id} ${valueId}`}
        aria-label={label ? undefined : ariaLabel}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        disabled={disabled}
        className={triggerClass}
        onClick={() => (open ? close() : openAt(selectedIndex >= 0 ? selectedIndex : firstEnabled))}
        onKeyDown={onKeyDown}
      >
        <span id={valueId} className={cx("flex min-w-0 items-center gap-2", !selected && !isPill && "text-ink-faint")}>
          {selected?.tone && <span className={cx("h-2 w-2 shrink-0 rounded-full", dot[selected.tone])} aria-hidden />}
          <span className="truncate">{selected ? selected.label : placeholder}</span>
        </span>
        <ChevronDown className={cx("h-4 w-4 shrink-0 transition-transform", isPill ? "opacity-70" : "text-ink-muted", open && "rotate-180")} aria-hidden />
      </button>
      {name && <input type="hidden" name={name} value={current ?? ""} />}
      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          tabIndex={-1}
          aria-labelledby={label ? labelId : undefined}
          aria-label={label ? undefined : ariaLabel}
          style={{ position: "fixed", top: pos.top, bottom: pos.bottom, left: pos.left, width: pos.width }}
          className="z-50 max-h-72 overflow-auto rounded-xl bg-white p-1 text-ink shadow-pop ring-1 ring-slate-900/10 animate-fade-in"
        >
          {options.map((o, i) => (
            <li
              key={o.value}
              id={optId(i)}
              role="option"
              aria-selected={i === selectedIndex}
              aria-disabled={o.disabled || undefined}
              onMouseMove={() => !o.disabled && active !== i && setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(i)}
              className={cx(
                "flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2",
                i === active && "bg-brand-50",
                o.disabled && "cursor-not-allowed opacity-50",
              )}
            >
              {o.tone && <span className={cx("h-2 w-2 shrink-0 rounded-full", dot[o.tone])} aria-hidden />}
              <span className="min-w-0 flex-1">
                <span className={cx("block text-sm", i === selectedIndex && "font-medium")}>{o.label}</span>
                {o.description && <span className="block text-xs text-ink-muted">{o.description}</span>}
              </span>
              {i === selectedIndex && <Check className="h-4 w-4 shrink-0 text-brand-600" aria-hidden />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  if (isPill) return <div className={className}>{body}</div>;
  return (
    <FieldShell id={id} hint={hint} error={error} className={className}>
      {label && (
        <label
          id={labelId}
          className="block text-sm font-medium text-ink"
          onClick={() => triggerRef.current?.focus()}
        >
          {label}
        </label>
      )}
      {body}
    </FieldShell>
  );
}
