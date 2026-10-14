/**
 * Perception types — the data contract for the Perception Overlay.
 *
 * The backend persists per-run perception frames as screenshot files and
 * grounding metadata.  The overlay renders an unavailable state only when a
 * run has not produced a frame or the API cannot retrieve one.
 */

/** A single candidate bounding box from the grounding/perception step */
export interface BoundingBox {
  /** Unique index within the frame (used for numbering) */
  index: number;
  /** [x, y, width, height] — normalized 0..1 or pixel coordinates */
  x: number;
  y: number;
  width: number;
  height: number;
  /** Confidence score 0..1 from the grounding model */
  confidence: number;
  /** Human-readable label for the target element */
  label: string;
  /** Whether the agent has selected this element as the action target */
  is_selected: boolean;
  /** Why the agent chose this element (planner reasoning) */
  reasoning?: string;
}

/** A single perception frame — screenshot + candidate boxes + action context */
export interface PerceptionFrame {
  /** Run step index */
  step_index: number;
  /** ISO 8601 timestamp when the frame was captured */
  timestamp: string;
  /** Base64-encoded PNG screenshot of the ServiceNow screen */
  screenshot_b64?: string;
  /** URL to the screenshot if served as a file */
  screenshot_url?: string;
  /** Authenticated API path to the screenshot (fetched with Bearer token) */
  screenshot_path?: string;
  /** All candidate bounding boxes evaluated in this step */
  boxes: BoundingBox[];
  /** The action the agent took (click, type, navigate, etc.) */
  action_taken?: string;
  /** The agent's stated reasoning for the action */
  action_reasoning?: string;
  /** The coordinates of the action target */
  target_coordinates?: { x: number; y: number };
}

/** The live run event frame — wraps a PerceptionFrame with run context */
export interface RunEventFrame {
  run_id: string;
  status: string;
  current_step: number;
  total_steps: number | null;
  perception?: PerceptionFrame;
  /** Whether this frame is from a live run vs. replay */
  is_live: boolean;
}
