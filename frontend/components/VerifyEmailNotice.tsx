"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, auth, ApiError } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui";
import { useToast } from "@/components/ui/Toast";

/** Message for a failed generation request when the account's email isn't confirmed yet. */
export function isEmailUnverified(e: unknown): boolean {
  return e instanceof ApiError && e.status === 403 && e.code === "email_unverified";
}

export const UNVERIFIED_MESSAGE = "Confirm your email first. We sent you a link when you signed up.";

type ResendState = "idle" | "busy" | "sent";

/** Resend action shared by the banner and the inline error. */
export function useResendVerification(onAlreadyVerified?: () => void) {
  const toast = useToast();
  const [state, setState] = useState<ResendState>("idle");

  async function resend() {
    setState("busy");
    try {
      const res = await auth.resendVerification();
      if (res?.status === "already_verified") {
        setState("idle");
        onAlreadyVerified?.();
        return;
      }
      setState("sent");
      toast.success("Sent. Check your inbox.");
    } catch (e) {
      setState("idle");
      toast.error(e instanceof ApiError && e.status === 429 ? "Please wait a bit before asking again." : e);
    }
  }
  return { state, resend };
}

/** "Resend email" button with inline confirmation. */
export function ResendEmailButton({ onAlreadyVerified, size = "sm" }: { onAlreadyVerified?: () => void; size?: "sm" | "md" }) {
  const { state, resend } = useResendVerification(onAlreadyVerified);
  if (state === "sent") return <span className="text-sm font-medium" role="status">Sent. Check your inbox.</span>;
  return (
    <Button size={size} variant="secondary" onClick={resend} loading={state === "busy"}>
      Resend email
    </Button>
  );
}

/** Slim banner for the signed-in shell. Renders nothing for verified users. */
export function VerifyEmailBanner() {
  const router = useRouter();
  const me = useResource(() => api.me());
  const [hidden, setHidden] = useState(false);
  const user = me.data;
  if (hidden || !user || user.email_verified_at !== null) return null;
  return (
    <div className="border-b border-amber-100 bg-amber-50 text-amber-900">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 text-sm sm:px-6">
        <p className="min-w-0 flex-1 basis-64">
          <span className="font-medium">Confirm your email to start tailoring.</span> We sent a link to{" "}
          <span className="break-all">{user.email}</span>.
        </p>
        <ResendEmailButton
          onAlreadyVerified={() => {
            setHidden(true);
            router.refresh();
          }}
        />
      </div>
    </div>
  );
}
