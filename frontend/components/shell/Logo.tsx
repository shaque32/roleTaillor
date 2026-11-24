import Link from "next/link";

export function Logo({ href = "/dashboard" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 font-semibold tracking-tight text-ink">
      <span className="grid h-7 w-7 place-items-center rounded-md bg-brand-600 text-xs font-bold text-white" aria-hidden>
        RT
      </span>
      RoleTailor
    </Link>
  );
}
