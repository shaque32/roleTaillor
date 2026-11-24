import { AlertCircle, Info, AlertTriangle } from "lucide-react";
import { cx } from "@/lib/format";

type Tone = "info" | "warning" | "error";
const styles: Record<Tone, string> = {
  info: "border-brand-100 bg-brand-50 text-brand-700",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  error: "border-red-200 bg-red-50 text-red-800",
};
const icons = { info: Info, warning: AlertTriangle, error: AlertCircle };

export function Alert({ tone = "info", title, children, className }: { tone?: Tone; title?: string; children?: React.ReactNode; className?: string }) {
  const Icon = icons[tone];
  return (
    <div className={cx("flex gap-3 rounded-md border px-4 py-3 text-sm", styles[tone], className)} role={tone === "error" ? "alert" : "status"}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div>{children}</div>}
      </div>
    </div>
  );
}
