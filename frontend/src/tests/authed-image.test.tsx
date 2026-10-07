import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthedImage } from "@/components/runs/AuthedImage";
import { setToken, clearToken } from "@/lib/auth-store";
import { api, ApiError } from "@/lib/api-client";

describe("AuthedImage", () => {
  const createObjectURLMock = vi.fn();
  const revokeObjectURLMock = vi.fn();

  beforeEach(() => {
    vi.restoreAllMocks();
    setToken("test-jwt-token-123");
    global.URL.createObjectURL = createObjectURLMock.mockReturnValue("blob:http://localhost/test-blob-url");
    global.URL.revokeObjectURL = revokeObjectURLMock;
  });

  afterEach(() => {
    clearToken();
    vi.clearAllMocks();
  });

  it("successfully loads authenticated screenshot and creates object URL", async () => {
    const mockBlob = new Blob(["fake-image-bytes"], { type: "image/png" });
    const getBlobSpy = vi.spyOn(api, "getBlob").mockResolvedValueOnce(mockBlob);

    render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
      />
    );

    await waitFor(() => {
      const img = screen.getByRole("img", { name: "Test Screenshot" });
      expect(img).toBeInTheDocument();
      expect(img).toHaveAttribute("src", "blob:http://localhost/test-blob-url");
    });

    expect(getBlobSpy).toHaveBeenCalledWith("/api/v1/screenshots/action_click_1.png", expect.any(AbortSignal));
    expect(createObjectURLMock).toHaveBeenCalledWith(mockBlob);
  });

  it("revokes object URL on unmount", async () => {
    const mockBlob = new Blob(["fake-image-bytes"], { type: "image/png" });
    vi.spyOn(api, "getBlob").mockResolvedValueOnce(mockBlob);

    const { unmount } = render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Test Screenshot" })).toBeInTheDocument();
    });

    unmount();
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:http://localhost/test-blob-url");
  });

  it("revokes previous object URL on path change", async () => {
    const mockBlob1 = new Blob(["image-1"], { type: "image/png" });
    const mockBlob2 = new Blob(["image-2"], { type: "image/png" });

    createObjectURLMock
      .mockReturnValueOnce("blob:http://localhost/blob-1")
      .mockReturnValueOnce("blob:http://localhost/blob-2");

    vi.spyOn(api, "getBlob")
      .mockResolvedValueOnce(mockBlob1)
      .mockResolvedValueOnce(mockBlob2);

    const { rerender } = render(
      <AuthedImage
        path="/api/v1/screenshots/frame1.png"
        alt="Frame 1"
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Frame 1" })).toHaveAttribute("src", "blob:http://localhost/blob-1");
    });

    rerender(
      <AuthedImage
        path="/api/v1/screenshots/frame2.png"
        alt="Frame 2"
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Frame 2" })).toHaveAttribute("src", "blob:http://localhost/blob-2");
    });

    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:http://localhost/blob-1");
  });

  it("handles 401 unauthorized error with diagnostic message", async () => {
    vi.spyOn(api, "getBlob").mockRejectedValueOnce(
      new ApiError(401, "Session expired. Please log in again.")
    );

    render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Screenshot unavailable (failed to load)")).toBeInTheDocument();
      expect(screen.getByText(/\[HTTP 401\]/)).toBeInTheDocument();
      expect(screen.getByText(/Unauthorized/i)).toBeInTheDocument();
    });
  });

  it("handles 403 forbidden error with diagnostic message", async () => {
    vi.spyOn(api, "getBlob").mockRejectedValueOnce(
      new ApiError(403, "Forbidden")
    );

    render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Screenshot unavailable (failed to load)")).toBeInTheDocument();
      expect(screen.getByText(/\[HTTP 403\]/)).toBeInTheDocument();
      expect(screen.getByText(/Forbidden/i)).toBeInTheDocument();
    });
  });

  it("handles 404 missing screenshot error with diagnostic message", async () => {
    vi.spyOn(api, "getBlob").mockRejectedValueOnce(
      new ApiError(404, "Screenshot not found")
    );

    render(
      <AuthedImage
        path="/api/v1/screenshots/missing.png"
        alt="Missing Screenshot"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Screenshot unavailable (failed to load)")).toBeInTheDocument();
      expect(screen.getByText(/\[HTTP 404\]/)).toBeInTheDocument();
      expect(screen.getByText(/Screenshot not found/i)).toBeInTheDocument();
    });
  });

  it("handles generic network error gracefully", async () => {
    vi.spyOn(api, "getBlob").mockRejectedValueOnce(new Error("Failed to fetch"));

    render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Screenshot unavailable (failed to load)")).toBeInTheDocument();
      expect(screen.getByText(/Failed to fetch/i)).toBeInTheDocument();
    });
  });

  it("handles 500 server error with diagnostic message", async () => {
    vi.spyOn(api, "getBlob").mockRejectedValueOnce(
      new ApiError(500, "Internal Server Error")
    );

    render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Screenshot unavailable (failed to load)")).toBeInTheDocument();
      expect(screen.getByText(/\[HTTP 500\]/)).toBeInTheDocument();
      expect(screen.getByText(/Server error/i)).toBeInTheDocument();
    });
  });

  it("invokes onLoad callback with dimensions when image finishes loading", async () => {
    const mockBlob = new Blob(["fake-image-bytes"], { type: "image/png" });
    vi.spyOn(api, "getBlob").mockResolvedValueOnce(mockBlob);
    const onLoadMock = vi.fn();

    render(
      <AuthedImage
        path="/api/v1/screenshots/action_click_1.png"
        alt="Test Screenshot"
        onLoad={onLoadMock}
      />
    );

    await waitFor(() => {
      const img = screen.getByRole("img", { name: "Test Screenshot" });
      expect(img).toBeInTheDocument();
    });

    const img = screen.getByRole("img", { name: "Test Screenshot" });
    // Fire image load event
    Object.defineProperty(img, "clientWidth", { value: 1920, configurable: true });
    Object.defineProperty(img, "clientHeight", { value: 1080, configurable: true });
    img.dispatchEvent(new Event("load"));

    expect(onLoadMock).toHaveBeenCalledWith({ width: 1920, height: 1080 });
  });
});
