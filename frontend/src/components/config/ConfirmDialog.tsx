/**
 * Reusable confirmation dialog component.
 *
 * Used for destructive actions like deleting profiles or changing defaults.
 */

import React from 'react';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/ui/button';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmButtonClass?: string;
  error?: string | null;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  confirmButtonClass = 'bg-red-500 hover:bg-red-600',
  error,
  loading,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  // Determine button variant based on confirm button class
  const isDestructive = confirmButtonClass?.includes('red');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md mx-4 rounded-lg border border-border bg-card shadow-lg">
        {/* Header */}
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        </div>

        {/* Body */}
        <div className="space-y-3 px-6 py-4">
          <p className="whitespace-pre-line text-sm text-foreground/90">{message}</p>

          {/* Error Message */}
          {error && (
            <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-6 py-4">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={loading}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={isDestructive ? 'destructive' : 'default'}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? 'Processing...' : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
};

