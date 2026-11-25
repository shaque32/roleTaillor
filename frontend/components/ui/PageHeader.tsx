import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { focusRing } from "./styles";
import { cx } from "@/lib/format";

export function PageHeader({
  title,
  description,
  actions,
  back,
  meta,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  back?: { href: string; label: string };
  meta?: React.ReactNode;
}) {
  return (
    <div className="mb-8">
      {back && (
        <Link href={back.href} className={cx("mb-3 inline-flex items-center gap-1.5 rounded-md text-sm text-ink-muted hover:text-ink", focusRing)}>
          <ArrowLeft className="h-4 w-4" aria-hidden />
          {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">{title}</h1>
          {meta && <div className="mt-2 flex flex-wrap items-center gap-2">{meta}</div>}
          {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}
