"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Mail, User } from "lucide-react";
import { auth, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Alert, Button, Input, PasswordInput, focusRing } from "@/components/ui";

function safeNext(next: string | null, fallback: string) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const email = String(fd.get("email") ?? "").trim();
    const password = String(fd.get("password") ?? "");
    const fullName = String(fd.get("full_name") ?? "").trim();
    const errs: Record<string, string> = {};
    if (!/^\S+@\S+\.\S+$/.test(email)) errs.email = "Enter a valid email address.";
    if (mode === "register" && password.length < 10) errs.password = "Use at least 10 characters.";
    if (mode === "register" && !fullName) errs.full_name = "Enter your name.";
    setFieldErrors(errs);
    const firstInvalid = (["full_name", "email", "password"] as const).find((k) => errs[k]);
    if (firstInvalid) {
      e.currentTarget.querySelector<HTMLInputElement>(`[name="${firstInvalid}"]`)?.focus();
      return;
    }

    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        await auth.login({ email, password, device_label: "web" });
        router.replace(safeNext(params.get("next"), "/dashboard"));
      } else {
        await auth.register({ email, password, full_name: fullName });
        router.replace("/onboarding");
      }
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That email and password don't match. Please try again."
          : err instanceof Error
            ? err.message
            : "Something went wrong.",
      );
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
      <p className="mt-2 text-sm text-ink-muted">
        {mode === "login" ? "Sign in to pick up where you left off." : "10 free tailored resumes. No card required."}
      </p>
      <form onSubmit={onSubmit} className="mt-7 space-y-5" noValidate>
        {mode === "login" && params.get("reset") === "1" && !error && (
          <Alert tone="success">Your password was changed. Sign in with your new password.</Alert>
        )}
        {error && <Alert tone="error">{error}</Alert>}
        {mode === "register" && (
          <Input name="full_name" label="Full name" autoComplete="name" required leading={<User />} error={fieldErrors.full_name} />
        )}
        <Input name="email" type="email" label="Email" autoComplete="email" required leading={<Mail />} error={fieldErrors.email} />
        <PasswordInput
          name="password"
          label="Password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          hint={mode === "register" ? "At least 10 characters." : undefined}
          error={fieldErrors.password}
        />
        {mode === "login" && (
          <p className="-mt-2 text-right text-sm">
            <Link href="/forgot-password" className={cx("rounded font-medium text-brand-700 hover:underline", focusRing)}>
              Forgot password?
            </Link>
          </p>
        )}
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          {mode === "login" ? (busy ? "Signing in…" : "Sign in") : busy ? "Creating your account…" : "Create account"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-ink-muted">
        {mode === "login" ? (
          <>
            New to RoleTailor?{" "}
            <Link href="/register" className={cx("rounded font-medium text-brand-700 hover:underline", focusRing)}>
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className={cx("rounded font-medium text-brand-700 hover:underline", focusRing)}>
              Sign in
            </Link>
          </>
        )}
      </p>
    </>
  );
}
