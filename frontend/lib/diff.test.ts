import { describe, expect, it } from "vitest";
import { applySide, diffPhrases, diffWords } from "./diff";

describe("diffWords", () => {
  it("returns a single equal segment for identical text", () => {
    expect(diffWords("Led a team of 5", "Led a team of 5")).toEqual([{ op: "equal", text: "Led a team of 5" }]);
  });

  it("marks word-level insertions and deletions", () => {
    const segs = diffWords("Built data pipelines in Python", "Built scalable data pipelines in Python and SQL");
    expect(segs.filter((s) => s.op === "insert").map((s) => s.text.trim())).toEqual(["scalable", "and SQL"]);
    expect(segs.some((s) => s.op === "delete")).toBe(false);
  });

  it("round-trips both sides", () => {
    const before = "Managed vendor relationships across three regions.";
    const after = "Owned vendor relationships across 3 regions, cutting costs 12%.";
    const segs = diffWords(before, after);
    expect(applySide(segs, "before")).toBe(before);
    expect(applySide(segs, "after")).toBe(after);
  });

  it("handles empty sides", () => {
    expect(diffWords("", "New text")).toEqual([{ op: "insert", text: "New text" }]);
    expect(diffWords("Old text", "")).toEqual([{ op: "delete", text: "Old text" }]);
  });
});

describe("diffPhrases", () => {
  it("reports ratio 0 for identical text", () => {
    const r = diffPhrases("Led a team of 5", "Led a team of 5");
    expect(r.ratio).toBe(0);
    expect(r.segments).toEqual([{ op: "equal", text: "Led a team of 5" }]);
  });

  it("highlights phrases, not single characters", () => {
    const before = "Data engineer who built pipelines for analytics";
    const after = "Data engineer who owned analytics pipelines end to end";
    const r = diffPhrases(before, after);
    expect(applySide(r.segments, "before")).toBe(before);
    expect(applySide(r.segments, "after")).toBe(after);
    const changed = r.segments.filter((s) => s.op !== "equal");
    expect(changed.length).toBeGreaterThan(0);
    expect(changed.every((s) => s.text.trim().length > 1)).toBe(true);
    // Never two deletes or two inserts in a row, and a delete always comes before its insert.
    r.segments.forEach((s, i) => {
      const prev = r.segments[i - 1];
      if (prev && prev.op !== "equal" && s.op !== "equal") expect(prev.op === "delete" && s.op === "insert").toBe(true);
    });
  });

  it("reports a high ratio for a reordered skills list", () => {
    const r = diffPhrases("Python, SQL, Airflow, dbt, Spark, Kafka", "Kafka, Spark, dbt, Airflow, SQL, Python");
    expect(r.ratio).toBeGreaterThan(0.6);
  });

  it("handles empty sides", () => {
    expect(diffPhrases("", "")).toEqual({ segments: [], ratio: 0 });
    const r = diffPhrases("", "New text");
    expect(r.segments).toEqual([{ op: "insert", text: "New text" }]);
    expect(r.ratio).toBe(1);
    expect(applySide(diffPhrases("Old text", "").segments, "before")).toBe("Old text");
  });
});
