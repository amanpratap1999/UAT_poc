import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, Sparkles, Wand2, Loader2 } from "lucide-react";
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

interface GeneratedCase {
  id: string;
  title: string;
  description: string;
  preconditions: string[];
  steps: any[];
  expected_outcomes: string[];
  risk_level: string;
}

export function NewRunDialog({ open, onClose }: NewRunDialogProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"direct" | "story">("direct");
  const [goal, setGoal] = useState("");
  const [story, setStory] = useState("");
  const [acceptanceCriteria, setAcceptanceCriteria] = useState("");
  const [generatedCases, setGeneratedCases] = useState<GeneratedCase[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createRunMutation = useMutation({
    mutationFn: (req: RunRequest) => api.post<RunResponse>("/api/v1/runs", req),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RUNS_QUERY_KEY });
      setGoal("");
      setStory("");
      setGeneratedCases([]);
      setError(null);
      onClose();
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.message : "Failed to start run. Please try again."
      );
    },
  });

  const handleDirectSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim()) return;
    setError(null);
    createRunMutation.mutate({ goal: goal.trim() });
  };

  const handleGenerateStory = async () => {
    if (!story.trim()) return;
    setIsGenerating(true);
    setError(null);
    try {
      const acList = acceptanceCriteria
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await api.generateTestCases({
        story: story.trim(),
        acceptance_criteria: acList,
        table_name: "incident",
        workflow_type: "incident",
      });
      setGeneratedCases(res.test_cases || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to generate test cases.");
    } finally {
      setIsGenerating(false);
    }
  };

  const executeTestCaseMutation = useMutation({
    mutationFn: (testCaseId: string) => api.executeTestCase(testCaseId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RUNS_QUERY_KEY });
      setGoal("");
      setStory("");
      setGeneratedCases([]);
      setError(null);
      onClose();
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.message : "Failed to execute test case. Please try again."
      );
    },
  });

  const handleExecuteCase = (tc: GeneratedCase) => {
    setError(null);
    executeTestCaseMutation.mutate(tc.id);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Start AI QA Agent Run"
      description="Run an autonomous test or synthesize structured test cases from a user story."
    >
      {/* Mode tabs */}
      <div className="mb-5 flex gap-1 rounded-lg border border-line bg-canvas p-1">
        <button
          type="button"
          onClick={() => setActiveTab("direct")}
          className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            activeTab === "direct"
              ? "bg-card text-ink shadow-card"
              : "text-muted hover:text-ink"
          }`}
        >
          Direct Goal
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("story")}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            activeTab === "story"
              ? "bg-card text-ink shadow-card"
              : "text-muted hover:text-ink"
          }`}
        >
          <Sparkles size={13} aria-hidden="true" />
          Story to Test Cases
        </button>
      </div>

      {activeTab === "direct" ? (
        <form onSubmit={handleDirectSubmit} className="flex flex-col gap-4">
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
      ) : (
        <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto pr-1">
          <div>
            <label htmlFor="run-story" className="mb-1.5 block text-xs font-semibold text-body">
              User Story / Feature Requirement
            </label>
            <textarea
              id="run-story"
              rows={3}
              value={story}
              onChange={(e) => setStory(e.target.value)}
              placeholder="As an IT support engineer, when I put an Incident On Hold with reason 'Awaiting Caller', the system must enforce caller communication and set hold reason correctly."
              className="w-full rounded-md border border-line bg-card p-2.5 font-body text-xs text-ink shadow-card placeholder:text-faint focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </div>

          <div>
            <label htmlFor="run-acceptance" className="mb-1.5 block text-xs font-semibold text-body">
              Acceptance Criteria (one per line, optional)
            </label>
            <textarea
              id="run-acceptance"
              rows={2}
              value={acceptanceCriteria}
              onChange={(e) => setAcceptanceCriteria(e.target.value)}
              placeholder={"- State changes to On Hold (value 3)\n- Hold reason is Awaiting Caller (value 1)\n- Work notes required"}
              className="w-full rounded-md border border-line bg-card p-2.5 font-body text-xs text-ink shadow-card placeholder:text-faint focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </div>

          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleGenerateStory}
              disabled={isGenerating || !story.trim()}
              className="gap-1.5"
            >
              {isGenerating ? (
                <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              ) : (
                <Wand2 size={13} aria-hidden="true" />
              )}
              Generate Test Cases
            </Button>
          </div>

          {generatedCases.length > 0 && (
            <div className="mt-2 flex flex-col gap-2">
              <p className="text-xs font-semibold text-ink">
                Generated Test Scenarios ({generatedCases.length}):
              </p>
              {generatedCases.map((tc) => (
                <div
                  key={tc.id}
                  className="rounded-lg border border-line bg-card p-3 shadow-card transition-all hover:border-accent/40 hover:shadow-raise"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-ink/[0.08] px-1.5 py-0.5 font-mono text-3xs font-bold text-body">
                          {tc.id}
                        </span>
                        <span className="text-xs font-medium text-ink">{tc.title}</span>
                      </div>
                      <p className="mt-1 text-2xs leading-relaxed text-body">{tc.description}</p>
                      {tc.preconditions.length > 0 && (
                        <p className="mt-1 font-mono text-3xs text-status-blocked">
                          Preconditions: {tc.preconditions.join("; ")}
                        </p>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => handleExecuteCase(tc)}
                      disabled={createRunMutation.isPending || executeTestCaseMutation.isPending}
                      className="shrink-0 gap-1 text-xs"
                    >
                      <Play size={11} className="fill-current" aria-hidden="true" />
                      Run
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {error && (
            <p role="alert" className="text-xs text-status-failed">
              {error}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}
