import { describe, expect, it } from "vitest";
import { parseHashToken } from "./hash-token";

describe("parseHashToken", () => {
  it("reads the token from a fragment", () => {
    expect(parseHashToken("#token=abc_DEF-123")).toBe("abc_DEF-123");
    expect(parseHashToken("token=abc")).toBe("abc");
    expect(parseHashToken("#a=1&token=xyz")).toBe("xyz");
  });
  it("returns null when missing or empty", () => {
    expect(parseHashToken("")).toBeNull();
    expect(parseHashToken("#")).toBeNull();
    expect(parseHashToken("#token=")).toBeNull();
    expect(parseHashToken("#other=1")).toBeNull();
  });
});
