import { cx } from "@/lib/format";

const variants = {
  raised: "rounded-xl bg-white shadow-card ring-1 ring-slate-900/5",
  flat: "rounded-xl bg-white ring-1 ring-line",
  sunken: "rounded-xl bg-surface-sunken",
};

export function Card({
  className,
  children,
  as: Tag = "div",
  variant = "raised",
}: {
  className?: string;
  children: React.ReactNode;
  as?: "div" | "section" | "article";
  variant?: "raised" | "flat" | "sunken";
}) {
  return <Tag className={cx(variants[variant], className)}>{children}</Tag>;
}

export function CardHeader({ title, description, action }: { title: React.ReactNode; description?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 px-5 pb-0 pt-5 sm:px-6 sm:pt-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cx("px-5 py-5 sm:px-6 sm:py-6", className)}>{children}</div>;
}

/** Unboxed section: heading row, then content. Use instead of a Card for lists or when nested in a Card. */
export function Section({
  title,
  description,
  action,
  id,
  className,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  id?: string;
  className?: string;
  children: React.ReactNode;
}) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section id={id} aria-labelledby={headingId} className={className}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-lg font-semibold text-ink">
            {title}
          </h2>
          {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
        </div>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}
