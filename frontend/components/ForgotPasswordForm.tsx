"use client";

import { useState } from "react";
import { Mail } from "lucide-react";
import { auth, ApiError } from "@/lib/api";
import { Alert, Button, Input } from "@/components/ui";
import { AuthHeading, TextLink } from "@/components/AuthPageParts";

export function ForgotPasswordForm() {
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const email = String(new FormData(form).get("email") ?? "").trim();
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setFieldError("Enter a valid email address.");
      form.querySelector<HTMLInputElement>('[name="email"]')?.focus();
      return;
    }
    setFieldError(undefined);
    setError(null);
    setBusy(true);
    try {
      await auth.forgotPassword(email);
      setSentTo(email);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Please wait a bit before asking again.");
      } else if (err instanceof ApiError && err.code === "network_error") {
        setError(err.message);
      } else if (err instanceof ApiError && err.status >= 500) {
        setError(err.message);
      } else {
        // Same answer whether or not the account exists.
        setSentTo(email);
      }
    } finally {
      setBusy(false);
    }
  }

  if (sentTo) {
    return (
      <>
        <AuthHeading title="Check your email" />
        <Alert tone="success" className="mt-6">
          If an account exists for <span className="break-all font-medium">{sentTo}</span>, we sent a link to reset your password. It expires in 60 minutes.
        </Alert>
        <p className="mt-6 text-center text-sm text-ink-muted">
          <TextLink href="/login">Back to sign in</TextLink>
        </p>
      </>
    );
  }

  return (
    <>
      <AuthHeading title="Forgot your password?">Enter your email and we&apos;ll send you a link to choose a new one.</AuthHeading>
      <form onSubmit={onSubmit} className="mt-7 space-y-5" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <Input name="email" type="email" label="Email" autoComplete="email" required leading={<Mail />} error={fieldError} />
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          {busy ? "Sending…" : "Send reset link"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-ink-muted">
        Remembered it? <TextLink href="/login">Back to sign in</TextLink>
      </p>
    </>
  );
}
