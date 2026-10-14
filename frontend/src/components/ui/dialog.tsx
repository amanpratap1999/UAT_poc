import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";
import { X } from "lucide-react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Accessible modal dialog.
 * Uses native <dialog> for focus trapping and Escape key handling.
 */
export function Dialog({ open, onClose, title, description, children, className }: DialogProps) {
  const dialogRef = React.useRef<HTMLDialogElement>(null);

  React.useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [open]);

  React.useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => onClose();
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [onClose]);

  // Close on backdrop click
  const handleClick = (e: React.MouseEvent<HTMLDialogElement>) => {
    const rect = dialogRef.current?.getBoundingClientRect();
    if (rect && (
      e.clientX < rect.left || e.clientX > rect.right ||
      e.clientY < rect.top || e.clientY > rect.bottom
    )) {
      onClose();
    }
  };

  return (
    <dialog
      ref={dialogRef}
      className={cn(
        "surface-elevated w-full max-w-lg rounded-xl p-0",
        "open:animate-fade-in",
        className
      )}
      onClick={handleClick}
      aria-labelledby="dialog-title"
      aria-describedby={description ? "dialog-description" : undefined}
    >
      <div className="flex items-start justify-between border-b border-line p-5">
        <div>
          <h2 id="dialog-title" className="font-display text-base font-semibold text-ink">
            {title}
          </h2>
          {description && (
            <p id="dialog-description" className="mt-1 text-sm text-body">
              {description}
            </p>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="Close dialog"
          className="ml-4 shrink-0"
        >
          <X size={16} />
        </Button>
      </div>
      <div className="p-5">{children}</div>
    </dialog>
  );
}
