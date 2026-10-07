import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { AlertTriangle, ImageOff, Lock } from "lucide-react";

interface AuthedImageProps {
  /** API path (e.g. /api/v1/screenshots/foo.png) — fetched with Bearer auth */
  path: string;
  alt: string;
  className?: string;
  onLoad?: (dims: { width: number; height: number }) => void;
}

interface LoadErrorInfo {
  status?: number;
  message: string;
}

/**
 * Authed image — fetches a binary resource with the JWT Authorization header
 * (which a plain <img src> cannot do) and renders it from an object URL.
 * Revokes the object URL on unmount/path change.
 * Shows diagnostic error information (with HTTP status) on failure.
 */
export function AuthedImage({ path, alt, className, onLoad }: AuthedImageProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<LoadErrorInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setError(null);
    setUrl(null);
    setIsLoading(true);

    const controller = new AbortController();

    api
      .getBlob(path, controller.signal)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setIsLoading(false);
        if (err instanceof ApiError) {
          setError({
            status: err.status,
            message:
              err.status === 401
                ? "Unauthorized (session expired or missing token)"
                : err.status === 403
                ? "Forbidden (insufficient permissions)"
                : err.status === 404
                ? "Screenshot not found"
                : err.status === 400
                ? "Invalid screenshot filename"
                : err.status === 500
                ? `Server error: ${err.message}`
                : `HTTP ${err.status}: ${err.message}`,
          });
        } else if (err instanceof Error && err.name !== "AbortError") {
          setError({ message: err.message || "Network error loading screenshot" });
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [path]);

  if (error) {
    const Icon =
      error.status === 401 || error.status === 403
        ? Lock
        : error.status === 404
        ? ImageOff
        : AlertTriangle;

    return (
      <div
        className="flex h-full w-full flex-col items-center justify-center gap-2 p-4 text-center"
        role="alert"
        aria-label="Screenshot unavailable"
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-graphite-600 bg-graphite-800 text-ink-400">
          <Icon size={18} aria-hidden="true" />
        </div>
        <div className="max-w-xs">
          <p className="font-mono text-xs font-medium text-ink-400">
            Screenshot unavailable (failed to load)
          </p>
          <p className="mt-1 font-mono text-[11px] text-ink-600">
            {error.status ? `[HTTP ${error.status}] ` : ""}
            {error.message}
          </p>
        </div>
      </div>
    );
  }

  if (isLoading || !url) {
    return (
      <div
        className={`flex items-center justify-center bg-graphite-950 ${className ?? "h-full w-full"}`}
        aria-label={alt}
      >
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-graphite-600 border-t-signal-teal" />
      </div>
    );
  }

  return (
    <img
      src={url}
      alt={alt}
      className={className}
      onLoad={(e) => {
        const img = e.currentTarget;
        onLoad?.({
          width: img.clientWidth || img.naturalWidth,
          height: img.clientHeight || img.naturalHeight,
        });
      }}
      onError={() => {
        setError({ message: "Failed to render image content" });
      }}
    />
  );
}
