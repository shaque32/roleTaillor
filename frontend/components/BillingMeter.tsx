"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { Skeleton } from "@/components/ui";

/** Small credit usage indicator from /billing/status. */
export function BillingMeter() {
  const { data, loading, error } = useResource(() => api.billing());
  if (loading) return <Skeleton className="h-10 w-48" />;
  if (error || !data) return null;
  if (data.subscription && data.subscription.status === "active") {
    return (
      <Link href="/settings#billing" className="text-sm text-ink-muted hover:text-ink">
        Subscription active
      </Link>
    );
  }
  const limit = Math.max(1, data.free_limit);
  const pct = Math.min(100, (data.free_used / limit) * 100);
  return (
    <Link href="/settings#billing" className="block w-52 rounded-md text-sm" aria-label={`${data.free_used} of ${data.free_limit} free generations used`}>
      <div className="flex justify-between text-ink-muted">
        <span>Free generations</span>
        <span className="tabular-nums text-ink">
          {data.free_used}/{data.free_limit}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-slate-200" aria-hidden>
        <div className={pct >= 100 ? "h-1.5 rounded-full bg-amber-500" : "h-1.5 rounded-full bg-brand-500"} style={{ width: `${pct}%` }} />
      </div>
      {data.pay_per_use_credits > 0 && <p className="mt-1 text-xs text-ink-muted">{data.pay_per_use_credits} paid credit(s) available</p>}
    </Link>
  );
}
