import type { LucideIcon } from "lucide-react";

export function EmptyState({ icon: Icon, title, description, action }: { icon?: LucideIcon; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      {Icon && (
        <div className="mb-4 rounded-full bg-brand-50 p-3 text-brand-600">
          <Icon className="h-6 w-6" aria-hidden />
        </div>
      )}
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {description && <p className="mt-1 max-w-md text-sm text-ink-muted">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
