/**
 * Anomaly classification categories.
 * Matches the AnomalyClassification enum in the backend domain layer.
 * NOTE: The FindingResponse.capability field carries a free-form string.
 * We map it to this enum for display using classifyCapability() below.
 */
export type AnomalyClassification =
  | "Business Rule Failure"
  | "Application Bug"
  | "Configuration Difference"
  | "Expected Customization"
  | "Agent Issue"
  | "Unknown";

/** Finding as returned by GET /api/v1/findings */
export interface Finding {
  id: string;
  tenant_id: string;
  run_id: string;
  capability: string; // backend free-form string
  description: string;
  is_defect: boolean;
  severity: string | null;
  created_at: string; // ISO 8601
}

/**
 * Classify a raw capability string into one of the known categories.
 * Used for badge colouring until the backend surfaces classification explicitly.
 */
export function classifyCapability(capability: string): AnomalyClassification {
  const lower = capability.toLowerCase();
  if (lower.includes("agent issue")) return "Agent Issue";
  if (lower.includes("business") || lower.includes("rule")) return "Business Rule Failure";
  if (lower.includes("bug") || lower.includes("application")) return "Application Bug";
  if (lower.includes("config") || lower.includes("configuration")) return "Configuration Difference";
  if (lower.includes("custom") || lower.includes("expected")) return "Expected Customization";
  return "Unknown";
}

/**
 * Classification colours as CSS variables — values are defined per-theme in
 * globals.css (--class-* tokens) so badges stay readable in both the light
 * workspace and the dark theater. Never signal-teal (Invariant 1).
 */
export const CLASSIFICATION_COLORS: Record<AnomalyClassification, string> = {
  "Business Rule Failure": "rgb(var(--class-business-rule))",
  "Application Bug": "rgb(var(--class-app-bug))",
  "Configuration Difference": "rgb(var(--class-config-diff))",
  "Expected Customization": "rgb(var(--class-expected-custom))",
  "Agent Issue": "rgb(var(--class-agent-issue))",
  "Unknown": "rgb(var(--class-unknown))",
};

export const CLASSIFICATION_BG: Record<AnomalyClassification, string> = {
  "Business Rule Failure": "rgb(var(--class-business-rule) / 0.1)",
  "Application Bug": "rgb(var(--class-app-bug) / 0.1)",
  "Configuration Difference": "rgb(var(--class-config-diff) / 0.1)",
  "Expected Customization": "rgb(var(--class-expected-custom) / 0.1)",
  "Agent Issue": "rgb(var(--class-agent-issue) / 0.1)",
  "Unknown": "rgb(var(--class-unknown) / 0.1)",
};
