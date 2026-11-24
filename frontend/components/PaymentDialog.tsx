"use client";

import { useState } from "react";
import { CreditCard, ExternalLink, Repeat } from "lucide-react";
import { api } from "@/lib/api";
import type { BillingStatus, CheckoutMode } from "@/lib/types";
import { Alert, Button, Dialog } from "@/components/ui";
import { cx } from "@/lib/format";

/**
 * Shown on 402 payment_required, before any paid credit is consumed.
 * The caller resends the workflow with accept_paid_usage: true via onAccept.
 */
export function PaymentDialog({
  open,
  onClose,
  onAccept,
  billing,
}: {
  open: boolean;
  onClose: () => void;
  onAccept: () => Promise<void>;
  billing: BillingStatus | null;
}) {
  const [checkoutStarted, setCheckoutStarted] = useState<CheckoutMode | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasPaidAccess = Boolean((billing?.subscription && billing.subscription.status === "active") || (billing?.pay_per_use_credits ?? 0) > 0);

  async function checkout(mode: CheckoutMode) {
    setBusy(mode);
    setError(null);
    const win = window.open("about:blank", "_blank");
    try {
      const { checkout_url } = await api.checkout(mode);
      if (win) {
        win.opener = null;
        win.location.href = checkout_url;
      } else {
        window.location.assign(checkout_url);
      }
      setCheckoutStarted(mode);
    } catch (e) {
      win?.close();
      setError(e instanceof Error ? e.message : "Couldn't start checkout.");
    } finally {
      setBusy(null);
    }
  }

  async function accept() {
    setBusy("accept");
    setError(null);
    try {
      await onAccept();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start tailoring.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="This tailoring uses paid credit"
      description={
        <>
          You&apos;ve used {billing ? `${billing.free_used} of ${billing.free_limit}` : "all of your"} free generations. We&apos;ll only
          charge for a generation that completes. Failed generations never count, and further iterations on this job are free.
        </>
      }
    >
      <div className="space-y-4">
        {hasPaidAccess ? (
          <Alert tone="info">
            {billing?.subscription?.status === "active"
              ? "Your subscription covers this generation."
              : `You have ${billing?.pay_per_use_credits} paid credit(s). This will use one.`}
          </Alert>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                { mode: "subscription", icon: Repeat, title: "Subscribe", price: "$9.99/month", body: "Tailor for as many roles as you need." },
                { mode: "pay_per_use", icon: CreditCard, title: "Pay for this resume", price: "$0.50", body: "One-time payment for this tailoring." },
              ] as const
            ).map((o) => (
              <button
                key={o.mode}
                onClick={() => checkout(o.mode)}
                disabled={busy !== null}
                className={cx(
                  "rounded-lg border p-4 text-left transition-colors hover:border-brand-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
                  checkoutStarted === o.mode ? "border-brand-500 bg-brand-50" : "border-slate-200",
                )}
              >
                <o.icon className="h-5 w-5 text-brand-600" aria-hidden />
                <p className="mt-2 text-sm font-semibold">{o.title}</p>
                <p className="text-lg font-semibold">{o.price}</p>
                <p className="mt-1 text-xs text-ink-muted">{o.body}</p>
                <p className="mt-2 inline-flex items-center gap-1 text-xs text-brand-600">
                  {busy === o.mode ? "Opening checkout…" : "Secure checkout"} <ExternalLink className="h-3 w-3" aria-hidden />
                </p>
              </button>
            ))}
          </div>
        )}
        {checkoutStarted && (
          <Alert tone="info">Checkout opened in a new tab. When payment is complete, come back here and continue.</Alert>
        )}
        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose}>
            Not now
          </Button>
          <Button onClick={accept} loading={busy === "accept"} disabled={!hasPaidAccess && !checkoutStarted}>
            {hasPaidAccess ? "Use paid credit and start" : "I've paid, start tailoring"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
