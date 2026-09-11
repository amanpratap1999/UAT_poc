import { CLASSIFICATION_COLORS, CLASSIFICATION_BG, classifyCapability } from "@/types/finding";
import type { AnomalyClassification } from "@/types/finding";

const LABEL: Record<AnomalyClassification, string> = {
  "Business Rule Failure": "Business Rule",
  "Application Bug": "App Bug",
  "Configuration Difference": "Config Diff",
  "Expected Customization": "Expected",
  "Agent Issue": "Agent Issue",
  "Unknown": "Unknown",
};

interface ClassificationBadgeProps {
  capability: string;
}

/**
 * Classification badge — theme-aware via CSS-variable colours.
 * NEVER uses signal-teal — that is reserved for perception/live state (Invariant 1).
 */
export function ClassificationBadge({ capability }: ClassificationBadgeProps) {
  const classification = classifyCapability(capability);
  const color = CLASSIFICATION_COLORS[classification];
  const bg = CLASSIFICATION_BG[classification];
  const label = LABEL[classification];

  return (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-2xs font-medium tracking-wide"
      style={{ color, backgroundColor: bg, borderColor: color }}
      title={classification}
    >
      {label}
    </span>
  );
}
