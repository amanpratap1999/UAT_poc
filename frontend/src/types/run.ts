/** Run status values from the backend. */
export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
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
