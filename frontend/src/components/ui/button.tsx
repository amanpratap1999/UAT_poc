import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // Base styles
  "inline-flex items-center justify-center gap-2 rounded font-body text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-teal focus-visible:ring-offset-2 focus-visible:ring-offset-graphite-950 disabled:pointer-events-none disabled:opacity-40 select-none",
  {
    variants: {
      variant: {
        primary:
          "bg-signal-teal text-graphite-950 hover:bg-signal-teal/90 active:bg-signal-teal/80",
        secondary:
          "bg-graphite-600 text-ink-100 border border-graphite-600 hover:bg-graphite-600/80",
        ghost:
          "text-ink-100 hover:bg-graphite-800 hover:text-ink-100",
        destructive:
          "bg-status-failed/15 text-status-failed border border-status-failed/30 hover:bg-status-failed/25",
        outline:
          "border border-graphite-600 text-ink-100 hover:bg-graphite-800",
      },
      size: {
        sm: "h-7 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-11 px-6 text-base",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, isLoading, children, disabled, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size, className }))}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading && (
          <span
            className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
            aria-hidden="true"
          />
        )}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

export { buttonVariants };
