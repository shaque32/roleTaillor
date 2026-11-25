import { forwardRef, useId, type InputHTMLAttributes } from "react";
import { cx } from "@/lib/format";
import { focusRing } from "./styles";

export const Checkbox = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: React.ReactNode; description?: React.ReactNode }
>(function Checkbox({ label, description, className, id: idProp, ...rest }, ref) {
  const auto = useId();
  const id = idProp ?? auto;
  return (
    <label htmlFor={id} className={cx("-m-3 flex cursor-pointer items-start gap-3 rounded-lg p-3 hover:bg-surface-sunken", className)}>
      <input
        ref={ref}
        id={id}
        type="checkbox"
        aria-describedby={description ? `${id}-desc` : undefined}
        className={cx("mt-0.5 h-5 w-5 shrink-0 cursor-pointer rounded-md border-line-field accent-brand-600", focusRing)}
        {...rest}
      />
      <span className="text-sm text-ink">
        {label}
        {description && (
          <span id={`${id}-desc`} className="mt-0.5 block text-ink-muted">
            {description}
          </span>
        )}
      </span>
    </label>
  );
});
