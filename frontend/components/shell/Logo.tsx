import Link from "next/link";
import { cx } from "@/lib/format";
import { focusRing } from "@/components/ui/styles";

export function Logo({ href = "/dashboard" }: { href?: string }) {
  return (
    <Link href={href} className={cx("flex items-center gap-2 rounded-lg text-base font-semibold tracking-tight text-ink", focusRing)}>
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-xs font-bold text-white" aria-hidden>
        RT
      </span>
      RoleTailor
    </Link>
  );
}
