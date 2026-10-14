import { useState } from "react";
import { formatConfidence } from "@/lib/utils";
import type { BoundingBox as BoundingBoxType } from "@/types/perception";

interface BoundingBoxProps {
  box: BoundingBoxType;
  /** Image dimensions for absolute pixel rendering */
  imageWidth: number;
  imageHeight: number;
  /** Whether to animate the reticle-pulse on the selected box */
  animatePulse?: boolean;
  onSelect?: (box: BoundingBoxType) => void;
}

/**
 * SVG bounding box — rendered as part of the PerceptionOverlay.
 *
 * signal-teal (#4DD8C4) is used ONLY here, as per design Invariant 1.
 * The reticle-pulse animation fires ONLY on the selected element.
 */
export function BoundingBox({
  box,
  imageWidth,
  imageHeight,
  animatePulse = false,
  onSelect,
}: BoundingBoxProps) {
  const [isHovered, setIsHovered] = useState(false);

  // Convert normalized [0..1] or pixel coords to SVG coordinates
  const isNormalized = box.x <= 1 && box.y <= 1 && box.width <= 1 && box.height <= 1;
  const px = isNormalized ? box.x * imageWidth : box.x;
  const py = isNormalized ? box.y * imageHeight : box.y;
  const pw = isNormalized ? box.width * imageWidth : box.width;
  const ph = isNormalized ? box.height * imageHeight : box.height;

  const TEAL = "#4DD8C4";
  const opacity = box.is_selected ? 1 : isHovered ? 0.8 : 0.55;
  const strokeWidth = box.is_selected ? 2 : 1.5;

  return (
    <g
      role="button"
      aria-label={`Element ${box.index}: ${box.label} — ${formatConfidence(box.confidence)} confidence`}
      tabIndex={0}
      style={{ cursor: "pointer" }}
      onClick={() => onSelect?.(box)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect?.(box)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Bounding box rect */}
      <rect
        x={px}
        y={py}
        width={pw}
        height={ph}
        fill="none"
        stroke={TEAL}
        strokeWidth={strokeWidth}
        strokeOpacity={opacity}
        rx={3}
        className={box.is_selected && animatePulse ? "animate-reticle-pulse" : undefined}
      />

      {/* Number badge */}
      <rect
        x={px}
        y={py - 18}
        width={20}
        height={18}
        fill={TEAL}
        fillOpacity={opacity}
        rx={3}
      />
      <text
        x={px + 10}
        y={py - 6}
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#14161A"
        fontSize={11}
        fontFamily="IBM Plex Mono, monospace"
        fontWeight={600}
      >
        {box.index}
      </text>

      {/* Confidence label — shown on selected or hovered */}
      {(box.is_selected || isHovered) && (
        <g>
          <rect
            x={px + pw + 4}
            y={py}
            width={52}
            height={20}
            fill="#1C1F26"
            fillOpacity={0.9}
            stroke={TEAL}
            strokeWidth={1}
            strokeOpacity={0.5}
            rx={3}
          />
          <text
            x={px + pw + 30}
            y={py + 10}
            textAnchor="middle"
            dominantBaseline="middle"
            fill={TEAL}
            fontSize={11}
            fontFamily="IBM Plex Mono, monospace"
          >
            {formatConfidence(box.confidence)}
          </text>
        </g>
      )}
    </g>
  );
}
