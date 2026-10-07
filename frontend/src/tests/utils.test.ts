import { describe, it, expect } from "vitest";
import { formatDuration, formatConfidence, truncate } from "@/lib/utils";

describe("formatDuration", () => {
  it("returns — for null", () => {
    expect(formatDuration(null)).toBe("—");
  });

  it("formats seconds under 60", () => {
    expect(formatDuration(45)).toBe("45s");
  });

  it("formats full minutes", () => {
    expect(formatDuration(120)).toBe("2m");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(135)).toBe("2m 15s");
  });
});

describe("formatConfidence", () => {
  it("formats 1.0 as 100%", () => {
    expect(formatConfidence(1.0)).toBe("100%");
  });

  it("formats 0.0 as 0%", () => {
    expect(formatConfidence(0)).toBe("0%");
  });

  it("formats 0.925 as 93%", () => {
    expect(formatConfidence(0.925)).toBe("93%");
  });
});

describe("truncate", () => {
  it("leaves short strings unchanged", () => {
    expect(truncate("hello", 10)).toBe("hello");
  });

  it("truncates long strings with ellipsis", () => {
    const result = truncate("a".repeat(100), 20);
    expect(result).toHaveLength(20);
    expect(result.endsWith("…")).toBe(true);
  });
});
