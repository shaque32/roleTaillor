"use client";
import { Badge, ChoiceCards, Disclosure, SegmentedControl } from "@/components/ui";
import { useConsentHint } from "./useConsentHint";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Download, ExternalLink } from "lucide-react";
import { api, auth } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import type { CheckoutMode, User, UserPatch } from "@/lib/types";
import { Alert, Button, Card, CardBody, CardHeader, Dialog, Input, PageHeader, SkeletonRows, useToast } from "@/components/ui";

const DELETE_PHRASE = "delete my account";

export function Settings() {
  const me = useResource(() => api.me());
  if (me.loading) return <SkeletonRows rows={6} />;
  if (me.error || !me.data) return <Alert tone="error">{me.error?.message ?? "Couldn't load your settings."}</Alert>;
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" />
      <div className="space-y-8">
        <ProfileCard user={me.data} onSaved={(u) => me.setData(u)} />
        <PreferencesCard user={me.data} onSaved={(u) => me.setData(u)} />
        <BillingCard />
        <DataCard />
      </div>
    </div>
  );
}

function useSave(onSaved: (u: User) => void) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function save(patch: UserPatch) {
    setBusy(true);
    try {
      onSaved(await api.updateMe(patch));
      toast.success("Saved.");
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }
  return { busy, save };
}

const str = (fd: FormData, k: string) => String(fd.get(k) ?? "").trim() || null;

function ProfileCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const { busy, save } = useSave(onSaved);
  return (
    <Card as="section">
      <CardHeader title="Profile" description={user.email} />
      <CardBody>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            void save({
              full_name: str(fd, "full_name") ?? user.full_name,
              contact_number: str(fd, "contact_number"),
              linkedin_url: str(fd, "linkedin_url"),
              address: { ...user.address, city: str(fd, "city") ?? undefined, country: str(fd, "country") ?? undefined },
            });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Input name="full_name" label="Full name" defaultValue={user.full_name} required autoComplete="name" />
            <Input name="contact_number" label="Phone" type="tel" defaultValue={user.contact_number ?? ""} autoComplete="tel" />
            <Input name="linkedin_url" label="LinkedIn URL" type="url" defaultValue={user.linkedin_url ?? ""} />
            <div className="grid grid-cols-2 gap-3">
              <Input name="city" label="City" defaultValue={user.address?.city ?? ""} autoComplete="address-level2" />
              <Input name="country" label="Country" defaultValue={user.address?.country ?? ""} autoComplete="country-name" />
            </div>
          </div>
          <Button type="submit" loading={busy}>
            Save profile
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function PreferencesCard({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const { busy, save } = useSave(onSaved);
  return (
    <Card as="section">
      <CardHeader title="Tailoring preferences" description="Defaults for every new tailoring. You can still change length per job." />
      <CardBody>
        <form
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            void save({
              preferred_page_limit: Number(fd.get("preferred_page_limit")) || 2,
              industry_focus: str(fd, "industry_focus"),
              resume_tone: str(fd, "resume_tone"),
              ats_preference: str(fd, "ats_preference"),
              technical_depth: str(fd, "technical_depth"),
              preferred_template_id: str(fd, "preferred_template_id"),
            });
          }}
        >
          <ChoiceCards
            name="preferred_page_limit"
            label="Resume length"
            columns={3}
            defaultValue={String(user.preferred_page_limit ?? 2)}
            options={[
              { value: "1", label: "1 page", description: "Early career or concise" },
              { value: "2", label: "2 pages", description: "Right for most roles", badge: "Recommended" },
              { value: "3", label: "3+ pages", description: "Senior, academic or federal" },
            ]}
          />
          <ChoiceCards
            name="resume_tone"
            label="Tone"
            columns={2}
            defaultValue={user.resume_tone ?? "professional"}
            options={[
              { value: "professional", label: "Professional", description: "Polished and neutral" },
              { value: "confident", label: "Confident", description: "Leads with impact" },
              { value: "concise", label: "Concise", description: "Short and direct" },
              { value: "warm", label: "Warm", description: "Personable and human" },
            ]}
          />
          <ChoiceCards
            name="ats_preference"
            label="Who should it read best for?"
            columns={3}
            defaultValue={user.ats_preference ?? "balanced"}
            options={[
              { value: "balanced", label: "Balanced", description: "Good for both", badge: "Recommended" },
              { value: "ats_first", label: "Screening software", description: "Simple structure, exact keywords" },
              { value: "human_first", label: "Human readers", description: "Natural flow and voice" },
            ]}
          />
          <SegmentedControl
            name="technical_depth"
            label="Technical detail"
            fullWidth
            defaultValue={user.technical_depth ?? "medium"}
            options={[
              { value: "low", label: "Light" },
              { value: "medium", label: "Moderate" },
              { value: "high", label: "Deep" },
            ]}
          />
          <p className="-mt-3 text-sm text-ink-muted">Light uses plain language. Deep keeps technical specifics.</p>
          <Input name="industry_focus" label="Industry focus" optional placeholder="e.g. Fintech, Healthcare" defaultValue={user.industry_focus ?? ""} />
          <Disclosure summary="Advanced">
            <div className="mt-3 max-w-sm">
              <Input
                name="preferred_template_id"
                label="Template ID"
                defaultValue={user.preferred_template_id ?? ""}
                hint="Used when re-rendering PDF uploads. Leave blank for the default template. DOCX uploads keep their own formatting."
              />
            </div>
          </Disclosure>
          <Button type="submit" loading={busy}>
            Save preferences
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function BillingCard() {
  const toast = useToast();
  const billing = useResource(() => api.billing());
  const [busy, setBusy] = useState<CheckoutMode | null>(null);
  const [portalBusy, setPortalBusy] = useState(false);
  const checkoutResult = useSearchParams().get("checkout");
  const { reload } = billing;

  useEffect(() => {
    if (checkoutResult !== "success") return;
    // The webhook may land a moment after the redirect; refetch a couple of times.
    const timers = [2000, 5000].map((ms) => setTimeout(() => void reload(), ms));
    return () => timers.forEach(clearTimeout);
  }, [checkoutResult, reload]);

  async function openPortal() {
    setPortalBusy(true);
    try {
      const { portal_url } = await api.portal();
      window.location.assign(portal_url);
    } catch (e) {
      toast.error(e);
      setPortalBusy(false);
    }
  }

  async function checkout(mode: CheckoutMode) {
    setBusy(mode);
    try {
      const { checkout_url } = await api.checkout(mode);
      window.location.assign(checkout_url);
    } catch (e) {
      toast.error(e);
      setBusy(null);
    }
  }

  const b = billing.data;
  const active = b?.subscription?.status === "active";
  const hasSubscription = !!b?.subscription;
  const pastDue = b?.subscription?.status === "past_due";
  const trialing = b?.subscription?.status === "trialing";
  return (
    <Card as="section">
      <div id="billing" className="scroll-mt-20" />
      <CardHeader title="Billing" description="Iterations on the same job are free. Failed generations never count." />
      <CardBody className="space-y-4">
        {checkoutResult === "success" && <Alert tone="info">Payment received. It can take a few seconds to show up.</Alert>}
        {checkoutResult === "cancelled" && <Alert tone="info">Checkout cancelled. You haven&apos;t been charged.</Alert>}
        {billing.loading && <SkeletonRows rows={1} />}
        {billing.error && <Alert tone="error">{billing.error.message}</Alert>}
        {b && (
          <>
            <dl className="grid gap-4 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-ink-muted">Free generations</dt>
                <dd className="mt-0.5 text-lg font-semibold tabular-nums">
                  {b.free_used} / {b.free_limit}
                </dd>
              </div>
              <div>
                <dt className="text-ink-muted">Paid credits</dt>
                <dd className="mt-0.5 text-lg font-semibold tabular-nums">{b.pay_per_use_credits}</dd>
              </div>
              <div>
                <dt className="text-ink-muted">Subscription</dt>
                <dd className="mt-0.5 text-lg font-semibold capitalize">{b.subscription ? b.subscription.status : "None"}</dd>
                {b.subscription?.current_period_end && (
                  <dd className="text-xs text-ink-muted">
                    {b.subscription.cancel_at_period_end ? "Ends" : "Renews"} {formatDate(b.subscription.current_period_end)}
                  </dd>
                )}
              </div>
            </dl>
            {pastDue && (
              <Alert tone="warning">
                Your last subscription payment failed. Update your payment method to keep generating.
                <Button className="ml-3" variant="secondary" onClick={openPortal} loading={portalBusy}>
                  Manage billing
                </Button>
              </Alert>
            )}
            <div className="flex flex-wrap gap-2">
              {!active && !trialing && !pastDue && (
                <Button onClick={() => checkout("subscription")} loading={busy === "subscription"}>
                  Subscribe · $9.99/month <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                </Button>
              )}
              <Button variant="secondary" onClick={() => checkout("pay_per_use")} loading={busy === "pay_per_use"}>
                Buy one resume · $0.50
              </Button>
              {hasSubscription && !pastDue && (
                <Button variant="ghost" onClick={openPortal} loading={portalBusy}>
                  Manage billing <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                </Button>
              )}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function DataCard() {
  const toast = useToast();
  const router = useRouter();
  const [exporting, setExporting] = useState(false);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [consentBusy, setConsentBusy] = useState(false);
  const [hint, setHint] = useConsentHint();
  const [withdrawOpen, setWithdrawOpen] = useState(false);

  async function setConsent(granted: boolean) {
    setConsentBusy(true);
    try {
      await api.grantConsent(granted);
      setHint(granted ? "granted" : "declined");
      setWithdrawOpen(false);
      toast.success(granted ? "AI processing consent granted." : "AI processing consent withdrawn. Tailoring is paused until you consent again.");
    } catch (e) {
      toast.error(e);
    } finally {
      setConsentBusy(false);
    }
  }

  async function exportData() {
    setExporting(true);
    try {
      const data = await api.exportMe();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `roletailor-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast.error(e);
    } finally {
      setExporting(false);
    }
  }

  async function deleteAccount() {
    setDeleting(true);
    try {
      await api.deleteMe();
      await auth.logout().catch(() => undefined);
      router.replace("/login");
      router.refresh();
    } catch (e) {
      toast.error(e);
      setDeleting(false);
    }
  }

  return (
    <Card as="section">
      <CardHeader title="Your data" />
      <CardBody className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
              AI processing consent
              {hint === "granted" && <Badge tone="green">Given on this device</Badge>}
              {hint === "declined" && <Badge tone="amber">Not given on this device</Badge>}
            </p>
            <p className="text-sm text-ink-muted">Required for tailoring. Withdrawing stops new AI processing of your resumes.</p>
          </div>
          <div className="flex gap-2">
            {hint !== "granted" && (
              <Button variant={hint === "declined" ? "primary" : "secondary"} onClick={() => setConsent(true)} loading={consentBusy}>
                Give consent
              </Button>
            )}
            <Button variant="secondary" onClick={() => setWithdrawOpen(true)} disabled={consentBusy}>
              Withdraw consent
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
          <div>
            <p className="text-sm font-medium">Export your data</p>
            <p className="text-sm text-ink-muted">Download everything we hold about you as JSON.</p>
          </div>
          <Button variant="secondary" onClick={exportData} loading={exporting}>
            <Download className="h-4 w-4" aria-hidden /> Export
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-6">
          <div>
            <p className="text-sm font-medium text-red-700">Delete account</p>
            <p className="text-sm text-ink-muted">Permanently delete your account, resumes and history.</p>
          </div>
          <Button variant="danger" onClick={() => setOpen(true)}>
            Delete account
          </Button>
        </div>
      </CardBody>
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setConfirm("");
        }}
        title="Delete your account?"
        description="This permanently deletes your account, resumes, tailored versions and application history. This can't be undone."
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" disabled={confirm.trim().toLowerCase() !== DELETE_PHRASE} loading={deleting} onClick={deleteAccount}>
              Permanently delete
            </Button>
          </>
        }
      >
        <Input label={`Type “${DELETE_PHRASE}” to confirm`} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
      </Dialog>
      <Dialog
        open={withdrawOpen}
        onClose={() => setWithdrawOpen(false)}
        size="sm"
        title="Withdraw AI consent?"
        description="You won't be able to tailor resumes until you give it again. Existing results stay available."
        footer={
          <>
            <Button variant="secondary" onClick={() => setWithdrawOpen(false)}>
              Keep consent
            </Button>
            <Button variant="danger" onClick={() => setConsent(false)} loading={consentBusy}>
              Withdraw
            </Button>
          </>
        }
      />
    </Card>
  );
}
