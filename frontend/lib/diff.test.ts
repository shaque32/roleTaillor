import { describe, expect, it } from "vitest";
import { applySide, diffWords } from "./diff";

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
