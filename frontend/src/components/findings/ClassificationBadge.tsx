import { CLASSIFICATION_COLORS, CLASSIFICATION_BG, classifyCapability } from "@/types/finding";
import type { AnomalyClassification } from "@/types/finding";

const LABEL: Record<AnomalyClassification, string> = {
  "Business Rule Failure": "Business Rule",
  "Application Bug": "App Bug",
  "Configuration Difference": "Config Diff",
  "Expected Customization": "Expected",
  "Unknown": "Unknown",
};

interface ClassificationBadgeProps {
  capability: string;
}

/**
 * Classification badge — uses four muted classification colours.
 * NEVER uses signal-teal — that is reserved for perception/live state (Invariant 1).
 */
export function ClassificationBadge({ capability }: ClassificationBadgeProps) {
  const classification = classifyCapability(capability);
  const color = CLASSIFICATION_COLORS[classification];
  const bg = CLASSIFICATION_BG[classification];
  const label = LABEL[classification];

  return (
    <span
      className="inline-flex items-center rounded-sm px-2 py-0.5 font-mono text-2xs font-medium uppercase tracking-wider"
      style={{ color, backgroundColor: bg }}
      title={classification}
    >
      {label}
    </span>
  );
}
