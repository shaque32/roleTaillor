"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { auth, ApiError } from "@/lib/api";
import { takeHashToken } from "@/lib/hash-token";
import { Alert, Button, ButtonLink, PasswordInput } from "@/components/ui";
import { AuthHeading, TextLink } from "@/components/AuthPageParts";

export function ResetPasswordForm() {
  const router = useRouter();
  const [token, setToken] = useState<string | null | undefined>(undefined); // undefined: not read yet
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setToken(takeHashToken());
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    const form = e.currentTarget;
    const fd = new FormData(form);
    const password = String(fd.get("password") ?? "");
    const confirm = String(fd.get("confirm") ?? "");
    const errs: Record<string, string> = {};
    if (password.length < 10) errs.password = "Use at least 10 characters.";
    if (confirm !== password) errs.confirm = "Passwords don't match.";
    setFieldErrors(errs);
    const first = (["password", "confirm"] as const).find((k) => errs[k]);
    if (first) {
      form.querySelector<HTMLInputElement>(`[name="${first}"]`)?.focus();
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await auth.resetPassword(token, password);
      router.replace("/login?reset=1");
      router.refresh();
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.code === "invalid_token") setExpired(true);
      else if (err instanceof ApiError && err.code === "weak_password") setFieldErrors({ password: "Use at least 10 characters." });
      else if (err instanceof ApiError && err.status === 429) setError("Please wait a bit before trying again.");
      else setError(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  if (token === undefined) return <AuthHeading title="Choose a new password" />;

  if (token === null || expired) {
    return (
      <>
        <AuthHeading title="Choose a new password" />
        <Alert tone="error" className="mt-6">
          {token === null ? "This reset link is missing or incomplete." : "This reset link is invalid or has expired."}
        </Alert>
        <ButtonLink href="/forgot-password" size="lg" className="mt-6 w-full">
          Request a new link
        </ButtonLink>
        <p className="mt-6 text-center text-sm text-ink-muted">
          <TextLink href="/login">Back to sign in</TextLink>
        </p>
      </>
    );
  }

  return (
    <>
      <AuthHeading title="Choose a new password">You&apos;ll be signed out everywhere else.</AuthHeading>
      <form onSubmit={onSubmit} className="mt-7 space-y-5" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <PasswordInput name="password" label="New password" autoComplete="new-password" required hint="At least 10 characters." error={fieldErrors.password} />
        <PasswordInput name="confirm" label="Confirm new password" autoComplete="new-password" required error={fieldErrors.confirm} />
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          {busy ? "Saving…" : "Change password"}
        </Button>
      </form>
    </>
  );
}
