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
    vi.spyOn(api, "importTestCases").mockResolvedValue([{
      test_cases: [{
        id: "TC-IMPORT-1",
        title: "Imported incident test",
        description: "Imported from XLSX",
        steps: [{ action_type: "select", target: "State", value: "In Progress" }],
        expected_outcomes: ["State is In Progress"],
      }],
      runs: [{ run_id: "run-import-1", status: "queued", message: "queued" }],
    }]);
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


  it("can queue imported workbook cases and links to the first created run", async () => {
    const { container } = render(<MemoryRouter><TestCases /></MemoryRouter>);
    const file = new File(["xlsx-content"], "incident-tests.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    fireEvent.change(screen.getByLabelText("Test case workbook"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Execute imported test cases after import" }));
    fireEvent.click(screen.getByRole("button", { name: /import xlsx/i }));

    await waitFor(() => {
      expect(api.importTestCases).toHaveBeenCalledWith(file, {
        personas: ["itil_user"],
        execute: true,
      });
    });
    expect(await screen.findByText("Imported incident test")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /open live run/i })).toHaveAttribute(
      "href",
      "/runs/run-import-1",
    );
    expect(container.querySelector('input[type="file"]')).not.toBeNull();
  });
