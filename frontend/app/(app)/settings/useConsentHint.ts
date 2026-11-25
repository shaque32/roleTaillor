"use client";

import { useEffect, useState } from "react";
import { getConsentHint, setConsentHint, type ConsentHint } from "@/lib/consent";

/** Device-local consent hint, read after mount to avoid a hydration mismatch. Setter also persists. */
export function useConsentHint(): [ConsentHint, (v: Exclude<ConsentHint, null>) => void] {
  const [hint, setHint] = useState<ConsentHint>(null);
  useEffect(() => setHint(getConsentHint()), []);
  return [
    hint,
    (v) => {
      setConsentHint(v);
      setHint(v);
    },
  ];
}
