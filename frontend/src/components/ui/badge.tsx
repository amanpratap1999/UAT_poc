import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-2xs font-medium tracking-wide",
  {
    variants: {
      variant: {
        default: "border-line bg-canvas text-muted",
        // Run status badges
        queued: "border-line bg-canvas text-muted",
        running: "border-status-running/30 bg-status-running/10 text-status-running",
        paused: "border-status-blocked/30 bg-status-blocked/10 text-status-blocked",
        awaiting_user_input:
          "border-status-running/40 bg-status-running/15 text-status-running animate-pulse",
        completed: "border-status-completed/30 bg-status-completed/10 text-status-completed",
        passed: "border-status-completed/30 bg-status-completed/10 text-status-completed",
        partial: "border-status-blocked/30 bg-status-blocked/10 text-status-blocked",
        failed: "border-status-failed/30 bg-status-failed/10 text-status-failed",
        precondition_failed: "border-status-blocked/30 bg-status-blocked/10 text-status-blocked",
        error: "border-status-failed/30 bg-status-failed/10 text-status-failed",
        blocked: "border-status-blocked/30 bg-status-blocked/10 text-status-blocked",
        cancelled: "border-line bg-canvas text-faint",
        // Classification badges — deliberately muted, never signal-teal
        "business-rule": "border-class-business-rule/30 bg-class-business-rule/10 text-class-business-rule",
        "app-bug": "border-class-app-bug/30 bg-class-app-bug/10 text-class-app-bug",
        "config-diff": "border-class-config-diff/30 bg-class-config-diff/10 text-class-config-diff",
        "expected-custom": "border-class-expected-custom/30 bg-class-expected-custom/10 text-class-expected-custom",
        "agent-issue": "border-class-agent-issue/30 bg-class-agent-issue/10 text-class-agent-issue",
        unknown: "border-line bg-canvas text-faint",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { badgeVariants };
