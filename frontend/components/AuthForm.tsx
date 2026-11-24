"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { auth, ApiError } from "@/lib/api";
import { Alert, Button, Input } from "@/components/ui";

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
    if (Object.keys(errs).length) return;

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
      <h1 className="text-xl font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h1>
      <p className="mt-1 text-sm text-ink-muted">
        {mode === "login" ? "Welcome back." : "10 free tailored resumes. No card required."}
      </p>
      <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        {mode === "register" && <Input name="full_name" label="Full name" autoComplete="name" required error={fieldErrors.full_name} />}
        <Input name="email" type="email" label="Email" autoComplete="email" required error={fieldErrors.email} />
        <Input
          name="password"
          type="password"
          label="Password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          hint={mode === "register" ? "At least 10 characters." : undefined}
          error={fieldErrors.password}
        />
        <Button type="submit" className="w-full" loading={busy}>
          {mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-ink-muted">
        {mode === "login" ? (
          <>
            New to RoleTailor?{" "}
            <Link href="/register" className="font-medium text-brand-600 hover:underline">
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-brand-600 hover:underline">
              Sign in
            </Link>
          </>
        )}
      </p>
    </>
  );
}
