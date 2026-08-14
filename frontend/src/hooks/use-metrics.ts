import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { Metrics } from "@/types/metrics";

export const METRICS_QUERY_KEY = ["metrics"] as const;

export function useMetrics() {
  return useQuery({
    queryKey: METRICS_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Metrics>("/api/v1/metrics", signal),
    staleTime: 60_000, // 1 minute
    refetchInterval: 60_000,
  });
}
