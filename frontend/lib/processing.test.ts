import { describe, expect, it } from "vitest";
import { isUnavailable, latestVersionOf, pollDelay, processingMessage, readingCopy, startedAtMs } from "./processing";
import type { ResumeProcessing } from "./types";

const failed = (error: ResumeProcessing["error"]): ResumeProcessing => ({ status: "failed", error, started_at: "2026-01-01T00:00:00Z" });

describe("pollDelay", () => {
  it("polls every 2 s, then backs off to 5 s after 30 s", () => {
    expect(pollDelay(0)).toBe(2000);
    expect(pollDelay(29_999)).toBe(2000);
    expect(pollDelay(30_000)).toBe(5000);
    expect(pollDelay(120_000)).toBe(5000);
  });
});

describe("processingMessage", () => {
  it("prefers the server message", () => {
    expect(processingMessage(failed({ code: "ocr_no_text", message: "No text found." }))).toBe("No text found.");
  });
  it("falls back per code, then generically", () => {
    expect(processingMessage(failed({ code: "ocr_timeout", message: " " }))).toMatch(/too long/);
    expect(processingMessage(failed({ code: "something_new", message: "" }))).toMatch(/couldn't read/);
    expect(processingMessage(failed(null))).toMatch(/couldn't read/);
    expect(processingMessage(null)).toMatch(/couldn't read/);
  });
});

describe("readingCopy", () => {
  it("changes wording after 45 s", () => {
    expect(readingCopy(10_000).detail).toMatch(/under a minute/);
    expect(readingCopy(45_000).detail).toMatch(/Still working/);
  });
});

describe("latestVersionOf", () => {
  it("returns the highest version number or null", () => {
    const v = (n: number) => ({ id: `v${n}`, version_number: n, created_at: "" });
    expect(latestVersionOf({ versions: [v(1), v(3), v(2)] })?.id).toBe("v3");
    expect(latestVersionOf({ versions: [] })).toBeNull();
  });
});

describe("isUnavailable / startedAtMs", () => {
  it("flags any non-null processing", () => {
    expect(isUnavailable({ processing: null })).toBe(false);
    expect(isUnavailable({ processing: failed(null) })).toBe(true);
  });
  it("clamps future or invalid timestamps", () => {
    expect(startedAtMs({ status: "processing", error: null, started_at: "nope" }, 1000)).toBe(1000);
    expect(startedAtMs({ status: "processing", error: null, started_at: "2999-01-01T00:00:00Z" }, 1000)).toBe(1000);
    expect(startedAtMs({ status: "processing", error: null, started_at: "1970-01-01T00:00:00.500Z" }, 1000)).toBe(500);
  });
});
