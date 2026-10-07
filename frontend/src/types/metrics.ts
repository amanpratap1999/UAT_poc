/**
 * Metrics response from GET /api/v1/metrics.
 * Metrics response from GET /api/v1/metrics, including terminal-run quality
 * rates and explicitly unavailable instrumentation fields.
 */
export interface Metrics {
  tenant_id: string;
  total_runs: number;
  total_defects: number;
  average_duration_seconds: number | null;
  terminal_runs: number;
  passed_runs: number;
  failed_runs: number;
  blocked_runs: number;
  pass_rate: number | null;
  defect_detection_rate: number | null;
  false_positive_rate: number | null;
  false_negative_rate: number | null;
  vision_fallback_rate: number | null;
  cost_per_run: number | null;
}

/** Computed/derived metrics (calculated client-side from available data) */
export interface DerivedMetrics {
  defects_per_run: number | null;
  defect_detection_rate: number | null;
  false_positive_rate: number | null;
  false_negative_rate: number | null;
  vision_fallback_rate: number | null;
  cost_per_run: number | null;
}
