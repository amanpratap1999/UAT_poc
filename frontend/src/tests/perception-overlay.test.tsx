import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PerceptionOverlay } from "@/components/runs/PerceptionOverlay";
import { evidenceToFrames, type PerceptionEvidenceResponse } from "@/hooks/use-run-perception";
import type { PerceptionFrame } from "@/types/perception";
import { api } from "@/lib/api-client";

describe("PerceptionOverlay", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.URL.createObjectURL = vi.fn().mockReturnValue("blob:http://localhost/test-blob");
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows unavailable state when no frame is provided", () => {
    render(<PerceptionOverlay />);
    expect(screen.getByText("Perception data unavailable")).toBeInTheDocument();
  });

  it("shows unavailable state when frame has no screenshot", () => {
    const frame: PerceptionFrame = {
      step_index: 0,
      timestamp: "2026-08-14T00:00:00Z",
      boxes: [],
    };
    render(<PerceptionOverlay frame={frame} />);
    expect(screen.getByText("Perception data unavailable")).toBeInTheDocument();
  });

  it("shows live indicator when isLive is true and screenshot exists", () => {
    const frame: PerceptionFrame = {
      step_index: 1,
      timestamp: "2026-08-14T00:00:00Z",
      screenshot_url: "http://example.com/screenshot.png",
      boxes: [],
    };
    render(<PerceptionOverlay frame={frame} isLive={true} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders bounding box toggle control", () => {
    const frame: PerceptionFrame = {
      step_index: 1,
      timestamp: "2026-08-14T00:00:00Z",
      screenshot_url: "http://example.com/screenshot.png",
      boxes: [
        {
          index: 1,
          x: 100,
          y: 100,
          width: 200,
          height: 50,
          confidence: 0.92,
          label: "Submit button",
          is_selected: true,
          reasoning: "Highest confidence target",
        },
      ],
    };
    render(<PerceptionOverlay frame={frame} isLive={false} />);
    expect(screen.getByRole("button", { name: /hide perception overlay/i })).toBeInTheDocument();
  });

  it("renders AuthedImage when screenshot_path is provided", async () => {
    const mockBlob = new Blob(["fake-image-bytes"], { type: "image/png" });
    vi.spyOn(api, "getBlob").mockResolvedValueOnce(mockBlob);

    const frame: PerceptionFrame = {
      step_index: 1,
      timestamp: "2026-08-14T00:00:00Z",
      screenshot_path: "/api/v1/screenshots/action_click_1.png",
      boxes: [],
    };

    render(<PerceptionOverlay frame={frame} isLive={false} />);

    await waitFor(() => {
      const img = screen.getByRole("img", { name: /ServiceNow screenshot — step 1/i });
      expect(img).toBeInTheDocument();
      expect(img).toHaveAttribute("src", "blob:http://localhost/test-blob");
    });
  });
});

describe("evidenceToFrames", () => {
  it("converts backend evidence to frontend PerceptionFrame array", () => {
    const backendResponse: PerceptionEvidenceResponse = {
      run_id: "test-run-123",
      status: "completed",
      frames: [
        {
          step_index: 2,
          timestamp: "2026-09-02T10:00:05Z",
          action_taken: "click: #submit_btn",
          action_reasoning: "Submitting form",
          screenshot_file: "action_click_2.png",
          perception: {
            route: "DOM",
            confidence: 0.98,
            target: "#submit_btn",
            bounding_box: {
              x: 120,
              y: 250,
              width: 180,
              height: 45,
            },
            locator: "button#submit_btn",
          },
        },
        {
          step_index: 1,
          timestamp: "2026-09-02T10:00:00Z",
          action_taken: "navigate: /incident.do",
          action_reasoning: "Opening incident form",
          screenshot_file: "action_navigate_1.png",
        },
      ],
    };

    const frames = evidenceToFrames(backendResponse);
    expect(frames).toHaveLength(2);
    // Should be sorted by step_index
    expect(frames[0].step_index).toBe(1);
    expect(frames[0].screenshot_path).toBe("/api/v1/screenshots/action_navigate_1.png");
    expect(frames[0].boxes).toHaveLength(0);

    expect(frames[1].step_index).toBe(2);
    expect(frames[1].screenshot_path).toBe("/api/v1/screenshots/action_click_2.png");
    expect(frames[1].boxes).toHaveLength(1);
    expect(frames[1].boxes[0].x).toBe(120);
    expect(frames[1].boxes[0].y).toBe(250);
    expect(frames[1].boxes[0].width).toBe(180);
    expect(frames[1].boxes[0].height).toBe(45);
    expect(frames[1].boxes[0].confidence).toBe(0.98);
  });

  it("filters out frames without screenshot_file", () => {
    const backendResponse: PerceptionEvidenceResponse = {
      run_id: "test-run-456",
      frames: [
        {
          step_index: 1,
          timestamp: "2026-09-02T10:00:00Z",
          action_taken: "extract: data",
          // No screenshot_file
        },
        {
          step_index: 2,
          timestamp: "2026-09-02T10:00:05Z",
          screenshot_file: "valid.png",
        },
      ],
    };

    const frames = evidenceToFrames(backendResponse);
    expect(frames).toHaveLength(1);
    expect(frames[0].screenshot_path).toBe("/api/v1/screenshots/valid.png");
  });
});
