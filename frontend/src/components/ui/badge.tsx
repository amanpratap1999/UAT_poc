import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-sm px-2 py-0.5 font-mono text-2xs font-medium uppercase tracking-wider",
  {
    variants: {
      variant: {
        default: "bg-graphite-600 text-ink-400",
        // Run status badges
        queued: "bg-ink-400/10 text-ink-400",
        running: "bg-signal-teal/15 text-signal-teal",
        completed: "bg-class-expected-custom/15 text-class-expected-custom",
        failed: "bg-status-failed/15 text-status-failed",
        blocked: "bg-amber-500/15 text-amber-500",
        cancelled: "bg-graphite-600 text-ink-600",
        // Classification badges — deliberately muted, never signal-teal
        "business-rule": "bg-class-business-rule/15 text-class-business-rule",
        "app-bug": "bg-class-app-bug/15 text-class-app-bug",
        "config-diff": "bg-class-config-diff/15 text-class-config-diff",
        "expected-custom": "bg-class-expected-custom/15 text-class-expected-custom",
        unknown: "bg-class-unknown/15 text-class-unknown",
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
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props} />
  );
}

export { badgeVariants };
