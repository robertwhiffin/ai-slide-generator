/**
 * Design System upload dialog.
 *
 * The headline Phase-4 capability: POST a .zip bundle to
 * /api/settings/design-systems/import. Surfaces 400/validation and 409 conflict
 * errors clearly, and reports the imported system to the parent on success.
 */

import React, { useState, useRef, useEffect } from 'react';
import { AlertCircle, UploadCloud } from 'lucide-react';
import { Button } from '@/ui/button';
import { configApi } from '../../api/config';
import type { DesignSystemDetail } from '../../api/config';

interface DesignSystemUploadDialogProps {
  isOpen: boolean;
  onUploaded: (imported: DesignSystemDetail) => void;
  onCancel: () => void;
}

export const DesignSystemUploadDialog: React.FC<DesignSystemUploadDialogProps> = ({
  isOpen,
  onUploaded,
  onCancel,
}) => {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reset when (re)opening.
  useEffect(() => {
    if (isOpen) {
      setFile(null);
      setName('');
      setError(null);
      setUploading(false);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !uploading) onCancel();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, uploading, onCancel]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Choose a .zip bundle to upload.');
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const imported = await configApi.importDesignSystem(file, name);
      onUploaded(imported);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import design system');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="flex w-full max-w-lg flex-col overflow-hidden rounded-lg border border-border bg-card shadow-xl">
        {/* Header */}
        <div className="border-b border-border bg-muted/30 px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">Upload design system</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Import a <code>.zip</code> bundle (manifest + tokens + brand assets + templates).
            It becomes an org-shared design system.
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col">
          <div className="space-y-4 p-6">
            {error && (
              <div
                className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
                role="alert"
              >
                <AlertCircle className="size-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* File picker */}
            <div>
              <label htmlFor="ds-file" className="mb-1 block text-sm font-medium text-foreground">
                Bundle file <span className="text-destructive">*</span>
              </label>
              <input
                id="ds-file"
                ref={fileInputRef}
                data-testid="design-system-file-input"
                type="file"
                accept=".zip,application/zip"
                disabled={uploading}
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setError(null);
                }}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground file:mr-3 file:rounded file:border-0 file:bg-primary/10 file:px-3 file:py-1 file:text-sm file:font-medium file:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              />
              {file && (
                <p className="mt-1 text-xs text-muted-foreground">Selected: {file.name}</p>
              )}
            </div>

            {/* Optional name override */}
            <div>
              <label htmlFor="ds-name" className="mb-1 block text-sm font-medium text-foreground">
                Name <span className="text-xs font-normal text-muted-foreground">(optional)</span>
              </label>
              <input
                id="ds-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Override the manifest name (e.g. to import a copy)"
                maxLength={255}
                disabled={uploading}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Names must be unique. Provide a different name to import a copy of an existing system.
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 border-t border-border bg-muted/30 px-6 py-4">
            <Button type="button" variant="outline" onClick={onCancel} disabled={uploading}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={uploading}
              data-testid="design-system-upload-submit"
              className="gap-1.5"
            >
              <UploadCloud className="size-4" />
              {uploading ? 'Uploading…' : 'Upload'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
