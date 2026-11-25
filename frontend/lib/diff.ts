export type DiffOp = "equal" | "insert" | "delete";
export interface DiffSegment {
  op: DiffOp;
  text: string;
}

/** Splits into words and whitespace runs so whitespace is preserved in output. */
export function tokenize(text: string): string[] {
  return text.match(/\s+|[^\s]+/g) ?? [];
}

const MAX_CELLS = 400_000;

/**
 * Word-level diff using an LCS table. Adjacent segments of the same op are merged.
 * Falls back to delete-all + insert-all on very large inputs.
 */
export function diffWords(before: string, after: string): DiffSegment[] {
  const a = tokenize(before);
  const b = tokenize(after);
  const out: DiffSegment[] = [];
  const push = (op: DiffOp, text: string) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last && last.op === op) last.text += text;
    else out.push({ op, text });
  };

  // Trim common prefix and suffix to keep the table small.
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  push("equal", a.slice(0, start).join(""));

  const ma = a.slice(start, endA);
  const mb = b.slice(start, endB);
  const n = ma.length;
  const m = mb.length;

  if (n * m > MAX_CELLS) {
    push("delete", ma.join(""));
    push("insert", mb.join(""));
  } else {
    // dp[i][j] = LCS length of ma[i:] and mb[j:]
    const w = m + 1;
    const dp = new Uint32Array((n + 1) * w);
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i * w + j] = ma[i] === mb[j] ? dp[(i + 1) * w + j + 1]! + 1 : Math.max(dp[(i + 1) * w + j]!, dp[i * w + j + 1]!);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (ma[i] === mb[j]) {
        push("equal", ma[i]!);
        i++;
        j++;
      } else if (dp[(i + 1) * w + j]! >= dp[i * w + j + 1]!) {
        push("delete", ma[i]!);
        i++;
      } else {
        push("insert", mb[j]!);
        j++;
      }
    }
    while (i < n) push("delete", ma[i++]!);
    while (j < m) push("insert", mb[j++]!);
  }

  push("equal", a.slice(endA).join(""));
  return out;
}

/** Reconstruct either side from segments (used in tests and for copy actions). */
export function applySide(segments: DiffSegment[], side: "before" | "after"): string {
  return segments
    .filter((s) => s.op === "equal" || s.op === (side === "before" ? "delete" : "insert"))
    .map((s) => s.text)
    .join("");
}

/** Phrase-level view of diffWords. ratio = changed characters / total characters across both sides (0..1). */
export function diffPhrases(before: string, after: string): { segments: DiffSegment[]; ratio: number } {
  const words = diffWords(before, after);

  // Absorb short "bridge" equals (whitespace, "a", "to", "and") between two changes into both sides.
  const expanded: DiffSegment[] = [];
  words.forEach((s, i) => {
    const prev = words[i - 1];
    const next = words[i + 1];
    if (s.op === "equal" && prev && next && prev.op !== "equal" && next.op !== "equal" && s.text.trim().length <= 3) {
      expanded.push({ op: "delete", text: s.text }, { op: "insert", text: s.text });
    } else {
      expanded.push(s);
    }
  });

  // Normalise each run of changes into one delete followed by one insert.
  const segments: DiffSegment[] = [];
  let del = "";
  let ins = "";
  const flush = () => {
    if (del) segments.push({ op: "delete", text: del });
    if (ins) segments.push({ op: "insert", text: ins });
    del = "";
    ins = "";
  };
  for (const s of expanded) {
    if (s.op === "delete") del += s.text;
    else if (s.op === "insert") ins += s.text;
    else {
      flush();
      const last = segments[segments.length - 1];
      if (last && last.op === "equal") last.text += s.text;
      else segments.push({ ...s });
    }
  }
  flush();

  const total = before.length + after.length;
  const changed = segments.reduce((n, s) => (s.op === "equal" ? n : n + s.text.length), 0);
  return { segments, ratio: total === 0 ? 0 : changed / total };
}
