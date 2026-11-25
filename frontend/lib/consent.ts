/** Device-local hint about AI consent, only for UI copy. The server's 428 stays the source of truth. */
export type ConsentHint = "granted" | "declined" | null;

const KEY = "rt_ai_consent";

export function getConsentHint(): ConsentHint {
  try {
    if (typeof window === "undefined") return null;
    const v = window.localStorage.getItem(KEY);
    return v === "granted" || v === "declined" ? v : null;
  } catch {
    return null;
  }
}

export function setConsentHint(v: Exclude<ConsentHint, null>): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(KEY, v);
  } catch {
    /* storage unavailable: the hint is optional */
  }
}
