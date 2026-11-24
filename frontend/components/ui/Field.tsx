import { forwardRef, useId, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cx } from "@/lib/format";

const control =
  "block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-slate-50 aria-[invalid=true]:border-red-500";

interface FieldShell {
  label?: string;
  hint?: string;
  error?: string;
  className?: string;
}

function Shell({ id, label, hint, error, className, children }: FieldShell & { id: string; children: React.ReactNode }) {
  return (
    <div className={cx("space-y-1.5", className)}>
      {label && (
        <label htmlFor={id} className="block text-sm font-medium text-ink">
          {label}
        </label>
      )}
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function describedBy(id: string, hint?: string, error?: string) {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldShell>(function Input(
  { label, hint, error, className, id: idProp, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Shell id={id} label={label} hint={hint} error={error} className={className}>
      <input ref={ref} id={id} className={control} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...rest} />
    </Shell>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & FieldShell>(function Textarea(
  { label, hint, error, className, id: idProp, rows = 4, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Shell id={id} label={label} hint={hint} error={error} className={className}>
      <textarea ref={ref} id={id} rows={rows} className={control} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...rest} />
    </Shell>
  );
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & FieldShell>(function Select(
  { label, hint, error, className, id: idProp, children, ...rest },
  ref,
) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <Shell id={id} label={label} hint={hint} error={error} className={className}>
      <select ref={ref} id={id} className={control} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...rest}>
        {children}
      </select>
    </Shell>
  );
});
