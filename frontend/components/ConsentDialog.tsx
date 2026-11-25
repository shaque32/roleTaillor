"use client";

import { useEffect, useState } from "react";
import { Gift, Send, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { setConsentHint } from "@/lib/consent";
import { Alert, Button, Checkbox, Dialog } from "@/components/ui";

const POINTS = [
  {
    icon: Send,
    title: "Your text goes to AI providers",
    first: "To tailor your resume, its text and the job description are sent to Anthropic (Claude) and OpenAI-compatible model APIs.",
    rest: "Only the text needed for each step is sent. Your original files stay with RoleTailor.",
  },
  {
    icon: ShieldCheck,
    title: "Nothing is invented",
    first: "We only rephrase and reorder what you wrote.",
    rest: "Skills the job asks for that you don't show are listed as gaps, never added.",
  },
  {
    icon: Gift,
    title: "Fair credits",
    first: "Your first 10 tailored resumes are free.",
    rest: "Re-runs on the same job are free. Failed runs never count.",
  },
];

/** The three explanatory points, shared by onboarding and the dialog. */
export function ConsentPoints({ compact }: { compact?: boolean }) {
  // In the dialog the title is an h2, so points are h3; on the onboarding page (h1) they are h2.
  const Heading = compact ? "h3" : "h2";
  return (
    <ul className="space-y-5">
      {POINTS.map((p) => (
        <li key={p.title} className="flex gap-4">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
            <p.icon className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <Heading className="text-base font-semibold text-ink">{p.title}</Heading>
            <p className="mt-0.5 text-sm text-ink-muted">{compact ? p.first : `${p.first} ${p.rest}`}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Asks for AI-processing consent in place. Calls api.grantConsent(true), setConsentHint("granted"), then onGranted(). */
export function ConsentDialog({
  open,
  onClose,
  onGranted,
  confirmLabel,
}: {
  open: boolean;
  onClose: () => void;
  onGranted: () => void | Promise<void>;
  confirmLabel?: string;
}) {
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setAgreed(false);
      setError(null);
    }
  }, [open]);

  async function grant() {
    setBusy(true);
    setError(null);
    try {
      await api.grantConsent(true);
      setConsentHint("granted");
      await onGranted();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your consent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="md"
      title="One thing before we start"
      description="We need your OK to process your resume with AI. You can withdraw it any time in Settings."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Not now
          </Button>
          <Button onClick={grant} disabled={!agreed} loading={busy}>
            {confirmLabel ?? "Agree and continue"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <ConsentPoints compact />
        <Checkbox checked={agreed} onChange={(e) => setAgreed(e.target.checked)} label="I agree to my resume and job descriptions being processed by these AI providers." />
        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Dialog>
  );
}
