import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { FINDINGS_QUERY_KEY } from "./use-findings";
import type { Finding } from "@/types/finding";

export interface FindingUpdate {
  capability?: string;
  description?: string;
  is_defect?: boolean;
  severity?: string;
}

/** Update/override a finding via PATCH /api/v1/findings/{id}. */
export function useUpdateFinding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      update,
    }: {
      id: string;
      update: FindingUpdate;
    }) => api.patch<Finding>(`/api/v1/findings/${id}`, update),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: FINDINGS_QUERY_KEY });
    },
  });
}
