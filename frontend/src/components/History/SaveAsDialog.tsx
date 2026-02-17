import React, { useState, useEffect, useRef } from 'react';
import { Button } from '@/ui/button';

interface SaveAsDialogProps {
  isOpen: boolean;
  currentTitle: string;
  onSave: (title: string) => void;
  onCancel: () => void;
}

export const SaveAsDialog: React.FC<SaveAsDialogProps> = ({
  isOpen,
  currentTitle,
  onSave,
  onCancel,
}) => {
  const [title, setTitle] = useState(currentTitle);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setTitle(currentTitle);
      setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 100);
    }
  }, [isOpen, currentTitle]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (title.trim()) {
      onSave(title.trim());
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center px-4">
        {/* Backdrop */}
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
          onClick={onCancel}
        />

        {/* Dialog */}
        <div className="relative w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-xl">
          <h3 className="mb-4 text-lg font-semibold text-foreground">Save Session</h3>

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="session-name" className="mb-1 block text-sm font-medium text-foreground">
                Session Name
              </label>
              <input
                ref={inputRef}
                type="text"
                id="session-name"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                placeholder="Enter a name for this session"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Give your session a memorable name to find it later.
              </p>
            </div>

            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onCancel}>
                Cancel
              </Button>
              <Button type="submit" disabled={!title.trim()}>
                Save
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};

