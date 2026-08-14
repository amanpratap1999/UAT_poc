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
 * Classify a raw capability string into one of the four known categories.
 * Used for badge colouring until the backend surfaces classification explicitly.
 */
export function classifyCapability(capability: string): AnomalyClassification {
  const lower = capability.toLowerCase();
  if (lower.includes("business") || lower.includes("rule")) return "Business Rule Failure";
  if (lower.includes("bug") || lower.includes("application")) return "Application Bug";
  if (lower.includes("config") || lower.includes("configuration")) return "Configuration Difference";
  if (lower.includes("custom") || lower.includes("expected")) return "Expected Customization";
  return "Unknown";
}

export const CLASSIFICATION_COLORS: Record<AnomalyClassification, string> = {
  "Business Rule Failure": "#6B85C4",
  "Application Bug": "#E8A33D",
  "Configuration Difference": "#9B7FC7",
  "Expected Customization": "#7FA890",
  "Unknown": "#5A5750",
};

export const CLASSIFICATION_BG: Record<AnomalyClassification, string> = {
  "Business Rule Failure": "rgba(107,133,196,0.15)",
  "Application Bug": "rgba(232,163,61,0.15)",
  "Configuration Difference": "rgba(155,127,199,0.15)",
  "Expected Customization": "rgba(127,168,144,0.15)",
  "Unknown": "rgba(90,87,80,0.15)",
};
