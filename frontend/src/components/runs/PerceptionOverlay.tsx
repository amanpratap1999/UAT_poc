import { useState, useRef, useEffect } from "react";
import { Eye, EyeOff } from "lucide-react";
import { BoundingBox } from "./BoundingBox";
import { AuthedImage } from "./AuthedImage";
import type { PerceptionFrame, BoundingBox as BoundingBoxType } from "@/types/perception";
import { formatConfidence } from "@/lib/utils";

interface PerceptionOverlayProps {
  frame?: PerceptionFrame;
  /** Whether the run is currently live */
  isLive?: boolean;
}

/**
 * Perception Overlay — the signature visual element of this product.
 *
 * Renders numbered, confidence-scored SVG bounding boxes over a ServiceNow screenshot.
 * signal-teal is used ONLY here, per design Invariant 1.
 *
 * When no perception data is available (backend capability not yet implemented),
 * renders a clear placeholder explaining what's missing.
 */
export function PerceptionOverlay({ frame, isLive }: PerceptionOverlayProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [imgDimensions, setImgDimensions] = useState({ width: 0, height: 0 });
  const [selectedBox, setSelectedBox] = useState<BoundingBoxType | null>(null);
  const [overlayVisible, setOverlayVisible] = useState(true);

  const hasFrame = !!frame;
  const hasScreenshot = !!(frame?.screenshot_b64 || frame?.screenshot_url || frame?.screenshot_path);
  const hasBoxes = (frame?.boxes?.length ?? 0) > 0;

  const screenshotSrc = frame?.screenshot_b64
    ? `data:image/png;base64,${frame.screenshot_b64}`
    : frame?.screenshot_url;

  useEffect(() => {
    if (!imgRef.current || !screenshotSrc) return;
    const img = imgRef.current;
    const update = () =>
      setImgDimensions({ width: img.clientWidth, height: img.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(img);
    return () => observer.disconnect();
  }, [screenshotSrc]);

  // Clear selection when frame changes
  useEffect(() => setSelectedBox(null), [frame]);

  if (!hasFrame || !hasScreenshot) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-xl border border-graphite-600 bg-graphite-800">
          <Eye size={24} className="text-ink-600" aria-hidden="true" />
        </div>
        <div className="max-w-xs">
          <p className="font-mono text-sm text-ink-400">Perception data unavailable</p>
          <p className="mt-2 text-xs text-ink-600">
            The backend does not yet persist perception frames.{" "}
            <code className="font-mono">PerceptionFrame</code> data will appear here
            once the backend grounding step stores screenshots and bounding box coordinates.
          </p>
        </div>
      </div>
    );
  }

  const selectedBoxData = selectedBox ?? frame.boxes.find((b) => b.is_selected) ?? null;

  return (
    <div className="relative flex h-full w-full flex-col">
      {/* Controls */}
      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        {isLive && (
          <div className="flex items-center gap-1.5 rounded border border-signal-teal/30 bg-graphite-800/90 px-2.5 py-1.5">
            <span
              className="h-2 w-2 animate-pulse rounded-full bg-signal-teal"
              aria-hidden="true"
            />
            <span className="font-mono text-xs text-signal-teal">Live</span>
          </div>
        )}
        <button
          onClick={() => setOverlayVisible((v) => !v)}
          className="flex items-center gap-1.5 rounded border border-graphite-600 bg-graphite-800/90 px-2.5 py-1.5 font-mono text-xs text-ink-400 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal"
          aria-label={overlayVisible ? "Hide perception overlay" : "Show perception overlay"}
        >
          {overlayVisible ? (
            <EyeOff size={12} aria-hidden="true" />
          ) : (
            <Eye size={12} aria-hidden="true" />
          )}
          Overlay
        </button>
      </div>

      {/* Screenshot + SVG overlay */}
      <div className="relative flex flex-1 items-center justify-center overflow-hidden bg-graphite-950 p-2">
        <div className="relative inline-flex max-h-full max-w-full items-center justify-center">
          {frame.screenshot_path ? (
            <AuthedImage
              path={frame.screenshot_path}
              alt={`ServiceNow screenshot — step ${frame.step_index}`}
              className="max-h-[calc(100vh-14rem)] max-w-full h-auto w-auto object-contain rounded shadow-lg"
              onLoad={(dims) => setImgDimensions(dims)}
            />
          ) : (
            <img
              ref={imgRef}
              src={screenshotSrc}
              alt={`ServiceNow screenshot — step ${frame.step_index}`}
              className="max-h-[calc(100vh-14rem)] max-w-full h-auto w-auto object-contain rounded shadow-lg"
              onLoad={(e) => {
                const img = e.currentTarget;
                setImgDimensions({ width: img.clientWidth, height: img.clientHeight });
              }}
            />
          )}

          {overlayVisible && hasBoxes && imgDimensions.width > 0 && (
            <svg
              className="pointer-events-all absolute inset-0 h-full w-full"
              viewBox={`0 0 ${imgDimensions.width} ${imgDimensions.height}`}
              preserveAspectRatio="none"
              aria-label="Perception overlay — candidate bounding boxes"
              role="img"
            >
              {frame.boxes.map((box) => (
                <BoundingBox
                  key={box.index}
                  box={box}
                  imageWidth={imgDimensions.width}
                  imageHeight={imgDimensions.height}
                  animatePulse={box.is_selected}
                  onSelect={setSelectedBox}
                />
              ))}
            </svg>
          )}
        </div>
      </div>

      {/* Selected box detail panel */}
      {selectedBoxData && (
        <div className="border-t border-graphite-600 bg-graphite-800 p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span
                  className="flex h-5 w-5 items-center justify-center rounded bg-signal-teal font-mono text-xs font-bold text-graphite-950"
                  aria-hidden="true"
                >
                  {selectedBoxData.index}
                </span>
                <span className="font-mono text-sm text-ink-100">{selectedBoxData.label}</span>
                <span className="font-mono text-xs text-signal-teal">
                  {formatConfidence(selectedBoxData.confidence)}
                </span>
              </div>
              {selectedBoxData.reasoning && (
                <p className="mt-2 text-xs text-ink-400">{selectedBoxData.reasoning}</p>
              )}
              <p className="mt-1 font-mono text-2xs text-ink-600">
                x:{Math.round(selectedBoxData.x)} y:{Math.round(selectedBoxData.y)}{" "}
                {Math.round(selectedBoxData.width)}×{Math.round(selectedBoxData.height)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Action / step info */}
      {frame.action_taken && (
        <div className="border-t border-graphite-600 bg-graphite-950/60 px-4 py-2">
          <span className="data-label mr-2">Action</span>
          <span className="font-mono text-xs text-ink-100">{frame.action_taken}</span>
          {frame.target_coordinates && (
            <span className="ml-4 font-mono text-2xs text-ink-400">
              @({frame.target_coordinates.x},{frame.target_coordinates.y})
            </span>
          )}
        </div>
      )}
    </div>
  );
}
