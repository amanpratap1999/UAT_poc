/** Run status values from the backend. */
export type RunStatus =
  | "queued"
  | "running"
  | "paused"
  | "awaiting_user_input"
  | "completed"
  | "passed"
  | "partial"
  | "failed"
  | "precondition_failed"
  | "error"
  | "blocked"
  | "cancelled";

/** Lightweight run as returned by GET /api/v1/runs */
export interface Run {
  id: string;
  tenant_id: string;
  requester_id: string | null;
  goal: string;
  status: RunStatus;
  start_time: string; // ISO 8601
  end_time: string | null;
  duration_seconds: number | null;
  defect_count: number;
  cleanup_status?: string | null;
  cleanup_details?: string | null;
  api_verification_status?: string | null;
  telemetry?: Record<string, number>;
}

/** Alias — same schema as Run (backend returns same shape for list and detail) */
export type RunDetail = Run;

/** Request body for POST /api/v1/runs */
export interface RunRequest {
  goal: string;
}

/** Response from POST /api/v1/runs */
export interface RunResponse {
  session_id: string;
  status: string;
  message: string;
}

export interface LivePlanStep {
  step_index: number;
  description: string;
  expected_outcome: string;
  status: "pending" | "in_progress" | "success" | "failed" | "skipped" | "blocked";
  risk_level?: number | string;
  error?: string | null;
  observed_values?: Record<string, unknown>;
  expected_values?: Record<string, unknown>;
}

export interface ClarificationPrompt {
  request_id: string;
  question: string;
  context?: Record<string, unknown>;
  timestamp?: string;
}

export interface ApprovalPrompt {
  prompt_id: string;
  step_index: number;
  description: string;
  risk_score: number;
  target?: string;
  timestamp?: string;
}

export interface LiveRunEvent {
  run_id: string;
  event_type: string;
  timestamp: string;
  sequence?: number;
  payload?: Record<string, any>;
  step_index?: number;
  plan?: { steps: LivePlanStep[] };
  step?: LivePlanStep;
  reason?: string;
  clarification?: ClarificationPrompt;
  approval?: ApprovalPrompt;
  message?: string;
  error?: string;
}
