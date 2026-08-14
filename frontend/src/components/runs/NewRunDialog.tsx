import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api-client";
import { RUNS_QUERY_KEY } from "@/hooks/use-runs";
import type { RunRequest, RunResponse } from "@/types/run";

interface NewRunDialogProps {
  open: boolean;
  onClose: () => void;
}

export function NewRunDialog({ open, onClose }: NewRunDialogProps) {
  const queryClient = useQueryClient();
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createRunMutation = useMutation({
    mutationFn: (req: RunRequest) => api.post<RunResponse>("/api/v1/runs", req),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RUNS_QUERY_KEY });
      setGoal("");
      setError(null);
      onClose();
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.message : "Failed to start run. Please try again."
      );
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim()) return;
    setError(null);
    createRunMutation.mutate({ goal: goal.trim() });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Start a new run"
      description="The agent will autonomously navigate your ServiceNow instance and report findings."
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          id="run-goal"
          label="Testing Goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. Test the complete Incident lifecycle from creation to resolution"
          hint="Describe what you want the agent to test in plain language."
          disabled={createRunMutation.isPending}
          autoFocus
          required
        />

        {error && (
          <p role="alert" className="text-xs text-status-failed">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            disabled={createRunMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            id="start-run-submit"
            type="submit"
            variant="primary"
            isLoading={createRunMutation.isPending}
            disabled={!goal.trim()}
            className="gap-2"
          >
            <Play size={14} aria-hidden="true" />
            Start run
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
