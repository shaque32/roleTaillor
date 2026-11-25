"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { cx } from "@/lib/format";
import { Badge, Skeleton, focusRing } from "@/components/ui";

const pillClass = "inline-flex items-center gap-3 rounded-full bg-white px-4 py-2 text-sm shadow-card ring-1 ring-slate-900/5";

/** Small credit usage indicator from /billing/status. */
export function BillingMeter() {
  const { data, loading, error } = useResource(() => api.billing());
  if (loading) return <Skeleton className="h-10 w-48 !rounded-full" />;
  if (error || !data) return null;
  if (data.subscription && data.subscription.status === "active") {
    return (
      <Link href="/settings#billing" className={cx(pillClass, focusRing)} aria-label="Subscription active. Manage billing.">
        <Badge tone="green">Subscribed</Badge>
      </Link>
    );
  }
  const limit = Math.max(1, data.free_limit);
  const left = Math.max(0, data.free_limit - data.free_used);
  const pct = left > 0 ? Math.min(100, (left / limit) * 100) : 100;
  const paid = data.pay_per_use_credits;
  const label = `${left > 0 ? `${left} of ${data.free_limit} free tailorings left` : "Free tailorings used"}${
    paid > 0 ? `, ${paid} paid credit${paid === 1 ? "" : "s"}` : ""
  }`;
  return (
    <Link href="/settings#billing" className={cx(pillClass, focusRing)} aria-label={label}>
      <span className="whitespace-nowrap font-medium text-ink">{left > 0 ? `${left} free left` : "Free tailorings used"}</span>
      <span className="h-1.5 w-16 shrink-0 rounded-full bg-surface-sunken" aria-hidden>
        <span className={cx("block h-1.5 rounded-full", left === 0 ? "bg-amber-500" : "bg-brand-500")} style={{ width: `${pct}%` }} />
      </span>
      {paid > 0 && <span className="whitespace-nowrap text-ink-muted">· {paid} paid</span>}
    </Link>
  );
}
