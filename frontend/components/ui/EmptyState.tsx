import type { LucideIcon } from "lucide-react";
import { DotBackground } from "@/components/fx/DotBackground";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  secondaryAction,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  secondaryAction?: React.ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-white px-6 py-16 shadow-card ring-1 ring-slate-900/5">
      <DotBackground fade />
      <div className="relative flex flex-col items-center text-center">
        {Icon && (
          <div className="mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600">
            <Icon className="h-7 w-7" aria-hidden />
          </div>
        )}
        <h2 className="text-xl font-semibold text-ink">{title}</h2>
        {description && <p className="mt-2 max-w-md text-sm text-ink-muted">{description}</p>}
        {(action || secondaryAction) && (
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            {action}
            {secondaryAction}
          </div>
        )}
      </div>
    </div>
  );
}
