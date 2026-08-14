import { describe, it, expect } from "vitest";
import { classifyCapability, CLASSIFICATION_COLORS } from "@/types/finding";

describe("classifyCapability", () => {
  it("classifies business rule capabilities", () => {
    expect(classifyCapability("business_rule_check")).toBe("Business Rule Failure");
    expect(classifyCapability("rule_validation")).toBe("Business Rule Failure");
  });

  it("classifies application bug capabilities", () => {
    expect(classifyCapability("application_bug_detected")).toBe("Application Bug");
    expect(classifyCapability("bug_in_form")).toBe("Application Bug");
  });

  it("classifies configuration differences", () => {
    expect(classifyCapability("config_mismatch")).toBe("Configuration Difference");
    expect(classifyCapability("configuration_check")).toBe("Configuration Difference");
  });

  it("classifies expected customizations", () => {
    expect(classifyCapability("expected_customization")).toBe("Expected Customization");
    expect(classifyCapability("custom_field")).toBe("Expected Customization");
  });

  it("falls back to Unknown for unrecognised capabilities", () => {
    expect(classifyCapability("xyz_unknown_check")).toBe("Unknown");
    expect(classifyCapability("")).toBe("Unknown");
  });
});

describe("CLASSIFICATION_COLORS", () => {
  it("has a color for all known classifications", () => {
    const keys = Object.keys(CLASSIFICATION_COLORS);
    expect(keys).toContain("Business Rule Failure");
    expect(keys).toContain("Application Bug");
    expect(keys).toContain("Configuration Difference");
    expect(keys).toContain("Expected Customization");
    expect(keys).toContain("Unknown");
  });

  it("never uses signal-teal for classification colors", () => {
    const teal = "#4DD8C4".toLowerCase();
    for (const color of Object.values(CLASSIFICATION_COLORS)) {
      expect(color.toLowerCase()).not.toBe(teal);
    }
  });
});
