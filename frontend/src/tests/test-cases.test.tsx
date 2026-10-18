import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { api } from "@/lib/api-client";
import TestCases from "@/pages/TestCases";

vi.mock("@/hooks/use-servicenow-personas", () => ({
  useServiceNowPersonas: () => ({
    data: {
      personas: [{ name: "itil_user", role: "itil" }],
      active_persona: "itil_user",
      requires_persona: true,
    },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

describe("Test Cases execution flow", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "generateTestCases").mockResolvedValue({
      story_id: "story-1",
      count: 1,
      test_cases: [{
        id: "TC-1",
        title: "Incident state can be updated",
        description: "Verify an incident state update.",
        steps: [{ action_type: "select", target: "State", value: "In Progress" }],
        expected_outcomes: ["State is In Progress"],
      }],
    });
    vi.spyOn(api, "executeTestCase").mockResolvedValue({
      session_id: "run-123",
      status: "queued",
      message: "Agent run queued for test case",
    });
  });

  it("executes a generated test case with the selected persona and links to its live run", async () => {
    render(<MemoryRouter><TestCases /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Requirement"), {
      target: { value: "Incident State must transition to In Progress" },
    });
    fireEvent.click(screen.getByRole("button", { name: /generate test cases/i }));
    expect(await screen.findByText("Incident state can be updated")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^execute$/i }));
    await waitFor(() => {
      expect(api.executeTestCase).toHaveBeenCalledWith("TC-1", "itil_user");
    });
    expect(await screen.findByRole("link", { name: /open live run/i })).toHaveAttribute("href", "/runs/run-123");
  });
});
