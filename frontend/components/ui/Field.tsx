"use client";

import { forwardRef, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { AlertCircle, Eye, EyeOff } from "lucide-react";
import { cx } from "@/lib/format";
import { IconButton } from "./Button";
import { fieldControl } from "./styles";

export interface FieldShellProps {
  id: string;
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: string;
  optional?: boolean;
  className?: string;
  labelId?: string;
  children: React.ReactNode;
}

/** Label + control slot + hint/error. Public so custom controls (Select, groups) share the same chrome. */
export function FieldShell({ id, label, hint, error, optional, className, labelId, children }: FieldShellProps) {
  return (
    <div className={cx("space-y-2", className)}>
      {label && (
        <label id={labelId} htmlFor={id} className="block text-sm font-medium text-ink">
          {label}
          {optional && <span className="font-normal text-ink-muted"> (optional)</span>}
        </label>
      )}
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-sm text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="flex items-start gap-1.5 text-sm text-red-700" role="alert">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}

export function describedBy(id: string, hint?: React.ReactNode, error?: string) {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

interface FieldExtras {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: string;
  className?: string;
  optional?: boolean;
}

export type InputProps = InputHTMLAttributes<HTMLInputElement> & FieldExtras & { leading?: React.ReactNode };

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, className, optional, leading, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  const input = (
    <input
      ref={ref}
      id={id}
      className={cx(fieldControl, "h-12", leading ? "pl-10" : undefined)}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy(id, hint, error)}
      {...rest}
    />
  );
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} optional={optional} className={className}>
      {leading ? (
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-ink-faint [&>svg]:h-4 [&>svg]:w-4" aria-hidden>
            {leading}
          </span>
          {input}
        </div>
      ) : (
        input
      )}
    </FieldShell>
  );
});

export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, "type">>(function PasswordInput(
  { label, hint, error, className, optional, leading, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  const [shown, setShown] = useState(false);
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} optional={optional} className={className}>
      <div className="relative">
        {leading && (
          <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-ink-faint [&>svg]:h-4 [&>svg]:w-4" aria-hidden>
            {leading}
          </span>
        )}
        <input
          ref={ref}
          id={id}
          type={shown ? "text" : "password"}
          className={cx(fieldControl, "h-12 pr-12", leading ? "pl-10" : undefined)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, hint, error)}
          {...rest}
        />
        <IconButton
          label={shown ? "Hide password" : "Show password"}
          size="sm"
          aria-pressed={shown}
          onClick={() => setShown((s) => !s)}
          className="absolute right-1.5 top-1.5"
        >
          {shown ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
        </IconButton>
      </div>
    </FieldShell>
  );
});

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & FieldExtras & { autoGrow?: boolean; maxRows?: number };

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, className, optional, autoGrow, maxRows = 16, id: idProp, rows = 4, onInput, value, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  const inner = useRef<HTMLTextAreaElement | null>(null);
  const setRef = useCallback(
    (el: HTMLTextAreaElement | null) => {
      inner.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    },
    [ref],
  );
  const grow = useCallback(() => {
    const el = inner.current;
    if (!el || !autoGrow) return;
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const line = parseFloat(cs.lineHeight) || 24;
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
    const max = line * maxRows + pad;
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [autoGrow, maxRows]);
  useLayoutEffect(grow, [grow, value]);
  useEffect(() => {
    const el = inner.current;
    if (!el || !autoGrow || typeof ResizeObserver === "undefined") return;
    let width = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        grow();
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [grow, autoGrow]);
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} optional={optional} className={className}>
      <textarea
        ref={setRef}
        id={id}
        rows={rows}
        value={value}
        className={cx(fieldControl, "py-3 leading-relaxed", autoGrow && "resize-none")}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        onInput={(e) => {
          grow();
          onInput?.(e);
        }}
        {...rest}
      />
    </FieldShell>
  );
});
