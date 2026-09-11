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
      <div className="flex flex-col gap-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-semibold text-body"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "h-9 w-full rounded-md border border-line bg-card px-3 font-body text-sm text-ink shadow-card placeholder:text-faint",
            "transition-colors focus:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/20",
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
          <p id={`${inputId}-hint`} className="text-xs text-faint">
            {hint}
          </p>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";
