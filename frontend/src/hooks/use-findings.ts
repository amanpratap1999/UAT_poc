import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { Finding } from "@/types/finding";

export const FINDINGS_QUERY_KEY = ["findings"] as const;

export function useFindings() {
  return useQuery({
    queryKey: FINDINGS_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Finding[]>("/api/v1/findings", signal),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useFindingsByRun(runId: string | undefined) {
  const query = useFindings();
  return {
    ...query,
    data: query.data?.filter((f) => f.run_id === runId),
  };
}
