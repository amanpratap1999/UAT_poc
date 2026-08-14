import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PerceptionOverlay } from "@/components/runs/PerceptionOverlay";
import type { PerceptionFrame } from "@/types/perception";

describe("PerceptionOverlay", () => {
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
});
