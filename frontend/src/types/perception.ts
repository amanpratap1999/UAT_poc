/**
 * Perception types — the data contract for the Perception Overlay.
 *
 * NOTE: The backend does not currently persist perception frames.
 * The PerceptionOverlay component is built against this contract
 * and will render real data when the backend provides it.
 * For now, it renders a "Perception data unavailable" state.
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
