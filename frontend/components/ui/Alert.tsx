import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cx } from "@/lib/format";

type Tone = "info" | "warning" | "error" | "success";
const styles: Record<Tone, string> = {
  info: "bg-brand-50 text-brand-800",
  warning: "bg-amber-50 text-amber-900",
  error: "bg-red-50 text-red-800",
  success: "bg-emerald-50 text-emerald-800",
};
const icons = { info: Info, warning: AlertTriangle, error: AlertCircle, success: CheckCircle2 };

export function Alert({
  tone = "info",
  title,
  children,
  className,
  action,
}: {
  tone?: Tone;
  title?: string;
  children?: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}) {
  const Icon = icons[tone];
  return (
    <div className={cx("flex flex-wrap items-start gap-3 rounded-lg px-4 py-3.5 text-sm", styles[tone], className)} role={tone === "error" ? "alert" : "status"}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 basis-48 space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div>{children}</div>}
      </div>
      {action && <div className="shrink-0 max-sm:basis-full max-sm:pl-7">{action}</div>}
    </div>
  );
}
