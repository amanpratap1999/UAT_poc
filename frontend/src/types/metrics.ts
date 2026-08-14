/**
 * Metrics response from GET /api/v1/metrics.
 * NOTE: The backend currently returns only these three fields.
 * Defect detection rate, false positive/negative rate, vision-fallback rate,
 * and cost per run are NOT yet available from the backend.
 * Those metrics are documented as PARTIAL in the frontend implementation report.
 */
export interface Metrics {
  tenant_id: string;
  total_runs: number;
  total_defects: number;
  average_duration_seconds: number | null;
}

/** Computed/derived metrics (calculated client-side from available data) */
export interface DerivedMetrics {
  defects_per_run: number | null;
  /** These require backend instrumentation that does not yet exist: */
  defect_detection_rate: null; // BLOCKED
  false_positive_rate: null;   // BLOCKED
  false_negative_rate: null;   // BLOCKED
  vision_fallback_rate: null;  // BLOCKED
  cost_per_run: null;           // BLOCKED
}
