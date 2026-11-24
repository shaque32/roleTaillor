"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

/** Accessible modal built on the native <dialog> element (focus trap + Esc for free). */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
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
      aria-labelledby="dialog-title"
      className="w-[calc(100%-2rem)] max-w-lg rounded-lg border border-slate-200 p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      {open && (
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <h2 id="dialog-title" className="text-lg font-semibold text-ink">
              {title}
            </h2>
            <button onClick={onClose} className="text-ink-faint hover:text-ink" aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </div>
          {description && <div className="mt-2 text-sm text-ink-muted">{description}</div>}
          <div className="mt-5">{children}</div>
        </div>
      )}
    </dialog>
  );
}
