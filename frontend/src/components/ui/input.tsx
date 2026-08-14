import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, hint, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-medium uppercase tracking-widest text-ink-400"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "h-9 w-full rounded border border-graphite-600 bg-graphite-800 px-3 font-body text-sm text-ink-100 placeholder:text-ink-600",
            "transition-colors focus:border-signal-teal/60 focus:outline-none focus:ring-1 focus:ring-signal-teal/30",
            "disabled:cursor-not-allowed disabled:opacity-40",
            error && "border-status-failed/60 focus:border-status-failed/60 focus:ring-status-failed/20",
            className
          )}
          aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
          aria-invalid={!!error}
          {...props}
        />
        {error && (
          <p id={`${inputId}-error`} role="alert" className="text-xs text-status-failed">
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${inputId}-hint`} className="text-xs text-ink-600">
            {hint}
          </p>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";
