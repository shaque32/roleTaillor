"use client";

import { useState } from "react";
import { CreditCard, ExternalLink, Repeat } from "lucide-react";
import { api } from "@/lib/api";
import type { BillingStatus, CheckoutMode } from "@/lib/types";
import { Alert, Badge, Button, Dialog, focusRing } from "@/components/ui";
import { SpotlightCard } from "@/components/fx/SpotlightCard";
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
      size="lg"
      title="You've used your free tailorings"
      description={
        <>
          You&apos;ve used {billing ? `${billing.free_used} of ${billing.free_limit}` : "all of your"} free tailorings. We&apos;ll only charge for one
          that completes. Failed runs never count, and re-runs on this job are free.
        </>
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Not now
          </Button>
          <Button onClick={accept} loading={busy === "accept"} disabled={!hasPaidAccess && !checkoutStarted}>
            {hasPaidAccess ? "Use paid credit and start" : "I've paid, start tailoring"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {hasPaidAccess ? (
          <Alert tone="info">
            {billing?.subscription?.status === "active"
              ? "Your subscription covers this tailoring."
              : `You have ${billing?.pay_per_use_credits} paid ${billing?.pay_per_use_credits === 1 ? "credit" : "credits"}. This will use one.`}
          </Alert>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                {
                  mode: "subscription",
                  icon: Repeat,
                  title: "Subscribe",
                  price: "$9.99/month",
                  body: "Tailor for as many roles as you need.",
                  best: true,
                },
                {
                  mode: "pay_per_use",
                  icon: CreditCard,
                  title: "Pay for this resume",
                  price: "$0.50",
                  body: "One-time payment for this tailoring.",
                  best: false,
                },
              ] as const
            ).map((o) => (
              <SpotlightCard key={o.mode} className={cx("h-full", checkoutStarted === o.mode && "!ring-2 !ring-brand-500")}>
                <button
                  type="button"
                  onClick={() => checkout(o.mode)}
                  disabled={busy !== null}
                  className={cx("block h-full w-full rounded-xl p-4 text-left disabled:cursor-not-allowed disabled:opacity-60", focusRing)}
                >
                  <span className="flex items-start justify-between gap-2">
                    <span className="grid h-10 w-10 place-items-center rounded-lg bg-brand-50 text-brand-600">
                      <o.icon className="h-5 w-5" aria-hidden />
                    </span>
                    {o.best && <Badge tone="brand">Best value</Badge>}
                  </span>
                  <span className="mt-3 block text-sm font-semibold">{o.title}</span>
                  <span className="block text-2xl font-semibold">{o.price}</span>
                  <span className="mt-1 block text-sm text-ink-muted">{o.body}</span>
                  <span className="mt-3 inline-flex items-center gap-1 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
                    {busy === o.mode ? "Opening checkout…" : "Secure checkout"} <ExternalLink className="h-3 w-3" aria-hidden />
                  </span>
                </button>
              </SpotlightCard>
            ))}
          </div>
        )}
        {checkoutStarted && <Alert tone="info">Checkout opened in a new tab. Finish there, then come back and press the button below.</Alert>}
        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Dialog>
  );
}
