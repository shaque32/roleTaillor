"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { auth, ApiError } from "@/lib/api";
import { takeHashToken } from "@/lib/hash-token";
import { Alert, Button, ButtonLink, Spinner } from "@/components/ui";
import { AuthHeading } from "@/components/AuthPageParts";

type State = "working" | "success" | "invalid" | "error";

export function VerifyEmailStatus() {
  const router = useRouter();
  const [state, setState] = useState<State>("working");
  const [message, setMessage] = useState("");
  const started = useRef(false);
  const token = useRef<string | null>(null);

  const submit = useCallback(() => {
    if (!token.current) {
      setState("invalid");
      return;
    }
    setState("working");
    auth
      .verifyEmail(token.current)
      .then(() => {
        token.current = null;
        setState("success");
        router.refresh();
      })
      .catch((err) => {
        if (err instanceof ApiError && err.code === "invalid_token") setState("invalid");
        else {
          // The link was not spent, so it is kept (in memory only) for another try.
          setMessage(err instanceof ApiError && err.status === 429 ? "Please wait a bit before trying again." : err instanceof Error ? err.message : "Something went wrong.");
          setState("error");
        }
      });
  }, [router]);

  useEffect(() => {
    // Strict mode runs effects twice; the token is single use, so only call once.
    if (started.current) return;
    started.current = true;
    token.current = takeHashToken();
    submit();
  }, [submit]);

  return (
    <>
      <AuthHeading title="Confirm your email" />
      <div className="mt-6" aria-live="polite">
        {state === "working" && (
          <p className="flex items-center gap-3 text-sm text-ink-muted">
            <Spinner /> Confirming your email…
          </p>
        )}
        {state === "success" && <Alert tone="success">Your email is confirmed.</Alert>}
        {state === "invalid" && (
          <Alert tone="info">
            This link is invalid or was already used. If you already confirmed your email, you are all set. If not, you can request a new link from the banner in the app.
          </Alert>
        )}
        {state === "error" && <Alert tone="error">{message}</Alert>}
      </div>
      {state === "error" && (
        <Button size="lg" className="mt-6 w-full" onClick={submit}>
          Try again
        </Button>
      )}
      {(state === "success" || state === "invalid") && (
        <ButtonLink href="/dashboard" size="lg" className="mt-6 w-full">
          Continue
        </ButtonLink>
      )}
    </>
  );
}
