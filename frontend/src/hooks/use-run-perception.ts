import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { PerceptionFrame } from "@/types/perception";

export function runPerceptionQueryKey(runId: string) {
  return ["runs", runId, "perception"] as const;
}

/** Backend evidence frame — screenshot referenced by filename, not inline base64. */
export interface PerceptionEvidenceFrame {
  step_index: number;
  timestamp: string;
  action_taken?: string;
  action_reasoning?: string;
  screenshot_file?: string;
  perception?: {
    route?: string | null;
    confidence?: number | null;
    target?: string | null;
    bounding_box?: {
      x: number;
      y: number;
      width: number;
      height: number;
    } | null;
    locator?: string | null;
  };
}

export interface PerceptionEvidenceResponse {
  run_id: string;
  status?: string;
  frames: PerceptionEvidenceFrame[];
}

/**
 * Convert backend evidence frames into the PerceptionFrame contract the
 * overlay component already understands.
 *
 * Bounding boxes: the backend stores absolute pixel coordinates captured at
 * 1920x1080 viewport scale; the overlay renders them as pixel coords against
 * the rendered image (its SVG viewBox is the rendered image size).
 */
export function evidenceToFrames(evidence: PerceptionEvidenceResponse): PerceptionFrame[] {
  return evidence.frames
    .filter((f) => !!f.screenshot_file)
    .map((f) => ({
      step_index: f.step_index,
      timestamp: f.timestamp,
      screenshot_path: `/api/v1/screenshots/${f.screenshot_file}`,
      boxes: f.perception?.bounding_box
        ? [
            {
              index: 1,
              x: f.perception.bounding_box.x,
              y: f.perception.bounding_box.y,
              width: f.perception.bounding_box.width,
              height: f.perception.bounding_box.height,
              confidence: f.perception.confidence ?? 1,
              label: f.perception.target ?? f.action_taken ?? "target",
              is_selected: true,
              reasoning: f.action_reasoning,
            },
          ]
        : [],
      action_taken: f.action_taken,
      action_reasoning: f.action_reasoning,
      target_coordinates: f.perception?.bounding_box
        ? {
            x: f.perception.bounding_box.x + f.perception.bounding_box.width / 2,
            y: f.perception.bounding_box.y + f.perception.bounding_box.height / 2,
          }
        : undefined,
    }))
    .sort((a, b) => a.step_index - b.step_index) as PerceptionFrame[];
}

export function useRunPerception(runId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: runPerceptionQueryKey(runId ?? ""),
    queryFn: ({ signal }) =>
      api.get<PerceptionEvidenceResponse>(`/api/v1/runs/${runId}/perception`, signal),
    enabled: !!runId && enabled,
    staleTime: 2_000,
    refetchInterval: (query) => {
      // Poll while the run is live; stop once terminal and frames captured
      const data = query.state.data;
      if (!data) return 3_000;
      const liveStatuses = ["queued", "running"];
      if (liveStatuses.includes(data.status ?? "")) return 3_000;
      // If status just turned terminal but frames haven't arrived yet, do a couple quick retries
      if ((!data.frames || data.frames.length === 0) && query.state.dataUpdateCount < 6) {
        return 1_500;
      }
      return false;
    },
  });
}
