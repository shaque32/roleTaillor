import { ChevronRight } from "lucide-react";
import { cx } from "@/lib/format";
import { focusRing } from "./styles";

/** Native <details>: expandable extra content with a rotating chevron. */
export function Disclosure({
  summary,
  defaultOpen,
  children,
  className,
}: {
  summary: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <details open={defaultOpen} className={cx("group", className)}>
      <summary
        className={cx(
          "inline-flex min-h-9 cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-medium text-brand-700 hover:text-brand-800 [&::-webkit-details-marker]:hidden",
          focusRing,
        )}
      >
        <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" aria-hidden />
        {summary}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}
