/** Reads `token` from a URL fragment such as `#token=abc`. Returns null when absent or empty. */
export function parseHashToken(hash: string): string | null {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const token = params.get("token")?.trim();
  return token ? token : null;
}

/** Reads the token from the current address and removes the fragment so it doesn't linger in the address bar. */
export function takeHashToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = parseHashToken(window.location.hash);
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  return token;
}
