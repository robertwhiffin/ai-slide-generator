/**
 * Deck Prompt form modal.
 *
 * Used for creating and editing deck prompts.
 */

import React, { useState, useEffect } from 'react';
import { AlertCircle } from 'lucide-react';
import Editor from '@monaco-editor/react';
import { Button } from '@/ui/button';
import type { DeckPrompt, DeckPromptCreate, DeckPromptUpdate } from '../../api/config';

interface DeckPromptFormProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  prompt?: DeckPrompt;
  onSubmit: (data: DeckPromptCreate | DeckPromptUpdate) => Promise<void>;
  onCancel: () => void;
}

export const DeckPromptForm: React.FC<DeckPromptFormProps> = ({
  isOpen,
  mode,
  prompt,
  onSubmit,
  onCancel,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [promptContent, setPromptContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when opening
  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && prompt) {
        setName(prompt.name);
        setDescription(prompt.description || '');
        setCategory(prompt.category || '');
        setPromptContent(prompt.prompt_content);
      } else {
        setName('');
        setDescription('');
        setCategory('');
        setPromptContent('');
      }
      setError(null);
    }
  }, [isOpen, mode, prompt]);

  const validate = (): string | null => {
    if (!name.trim()) {
      return 'Name is required';
    }
    if (!promptContent.trim()) {
      return 'Prompt content is required';
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const data: DeckPromptCreate | DeckPromptUpdate = {
        name: name.trim(),
        description: description.trim() || null,
        category: category.trim() || null,
        prompt_content: promptContent,
      };
      await onSubmit(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="flex w-full max-w-4xl max-h-[90vh] flex-col overflow-hidden rounded-lg border border-border bg-card shadow-xl">
        {/* Header */}
        <div className="border-b border-border bg-muted/30 px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">
            {mode === 'create' ? 'Create Deck Prompt' : 'Edit Deck Prompt'}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Define a reusable prompt template for generating specific types of presentations.
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col overflow-y-auto">
          <div className="space-y-4 p-6">
            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                <AlertCircle className="size-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Name */}
            <div>
              <label htmlFor="prompt-name" className="mb-1 block text-sm font-medium text-foreground">
                Name <span className="text-destructive">*</span>
              </label>
              <input
                id="prompt-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Quarterly Business Review"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                maxLength={100}
                disabled={saving}
              />
            </div>

            {/* Description */}
            <div>
              <label htmlFor="prompt-description" className="mb-1 block text-sm font-medium text-foreground">
                Description
              </label>
              <textarea
                id="prompt-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of what this prompt is for..."
                className="flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                rows={2}
                disabled={saving}
              />
            </div>

            {/* Category */}
            <div>
              <label htmlFor="prompt-category" className="mb-1 block text-sm font-medium text-foreground">
                Category
              </label>
              <input
                id="prompt-category"
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g., Review, Report, Summary, Analysis"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                maxLength={50}
                disabled={saving}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Optional category for organizing prompts.
              </p>
            </div>

            {/* Prompt Content */}
            <div>
              <label className="mb-1 block text-sm font-medium text-foreground">
                Prompt Content <span className="text-destructive">*</span>
              </label>
              <div className="overflow-hidden rounded-md border border-input">
                <Editor
                  height="300px"
                  defaultLanguage="markdown"
                  value={promptContent}
                  onChange={(value) => setPromptContent(value || '')}
                  options={{
                    minimap: { enabled: false },
                    wordWrap: 'on',
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    fontSize: 13,
                    readOnly: saving,
                  }}
                />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Instructions for the AI on how to create this type of presentation.
                Include sections, data to query, and formatting guidelines.
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 border-t border-border bg-muted/30 px-6 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={onCancel}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving...' : mode === 'create' ? 'Create Prompt' : 'Save Changes'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

