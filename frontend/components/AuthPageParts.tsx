import Link from "next/link";
import { cx } from "@/lib/format";
import { focusRing } from "@/components/ui";

export function AuthHeading({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      {children && <p className="mt-2 text-sm text-ink-muted">{children}</p>}
    </>
  );
}

export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className={cx("rounded font-medium text-brand-700 hover:underline", focusRing)}>
      {children}
    </Link>
  );
}
