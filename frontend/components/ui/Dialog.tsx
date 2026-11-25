"use client";

import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";
import { cx } from "@/lib/format";
import { IconButton } from "./Button";

const sizes = { sm: "sm:max-w-md", md: "sm:max-w-lg", lg: "sm:max-w-2xl" };

/** Accessible modal built on the native <dialog> element (focus trap + Esc for free). */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  size = "md",
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  size?: "sm" | "md" | "lg";
  footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => e.button === 0 && e.target === e.currentTarget && onClose()}
      aria-labelledby={titleId}
      className={cx(
        "w-full max-w-none rounded-2xl rounded-b-none border-0 bg-white p-0 shadow-pop backdrop:bg-slate-900/50 open:animate-pop-in",
        "mb-0 mt-auto max-h-[90dvh] overflow-y-auto",
        "sm:mb-auto sm:w-[calc(100%-2rem)] sm:rounded-b-2xl",
        sizes[size],
      )}
    >
      {open && (
        <div className="p-6 sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <h2 id={titleId} className="text-lg font-semibold text-ink">
              {title}
            </h2>
            <IconButton label="Close" size="sm" onClick={onClose} className="-mr-2 -mt-1">
              <X className="h-5 w-5" aria-hidden />
            </IconButton>
          </div>
          {description && <div className="mt-2 text-sm text-ink-muted">{description}</div>}
          {children && <div className="mt-5">{children}</div>}
          {footer && <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}
