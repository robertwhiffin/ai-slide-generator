/**
 * Slide Style form modal.
 *
 * Used for creating and editing slide styles.
 */

import React, { useState, useEffect } from 'react';
import { AlertCircle } from 'lucide-react';
import Editor from '@monaco-editor/react';
import { Button } from '@/ui/button';
import type { SlideStyle, SlideStyleCreate, SlideStyleUpdate } from '../../api/config';

interface SlideStyleFormProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  style?: SlideStyle;
  onSubmit: (data: SlideStyleCreate | SlideStyleUpdate) => Promise<void>;
  onCancel: () => void;
}

export const SlideStyleForm: React.FC<SlideStyleFormProps> = ({
  isOpen,
  mode,
  style,
  onSubmit,
  onCancel,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [styleContent, setStyleContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when opening
  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && style) {
        setName(style.name);
        setDescription(style.description || '');
        setCategory(style.category || '');
        setStyleContent(style.style_content);
      } else {
        setName('');
        setDescription('');
        setCategory('');
        setStyleContent('');
      }
      setError(null);
    }
  }, [isOpen, mode, style]);

  const validate = (): string | null => {
    if (!name.trim()) {
      return 'Name is required';
    }
    if (!styleContent.trim()) {
      return 'Style content is required';
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
      const data: SlideStyleCreate | SlideStyleUpdate = {
        name: name.trim(),
        description: description.trim() || null,
        category: category.trim() || null,
        style_content: styleContent,
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
            {mode === 'create' ? 'Create Slide Style' : 'Edit Slide Style'}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Define visual styling rules for slide generation (typography, colors, layout).
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col overflow-hidden">
          {/* Scrollable Content */}
          <div className="flex-1 overflow-y-auto">
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
                <label htmlFor="style-name" className="mb-1 block text-sm font-medium text-foreground">
                  Name <span className="text-destructive">*</span>
                </label>
                <input
                  id="style-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Databricks Brand"
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  maxLength={100}
                  disabled={saving}
                />
              </div>

              {/* Description */}
              <div>
                <label htmlFor="style-description" className="mb-1 block text-sm font-medium text-foreground">
                  Description
                </label>
                <textarea
                  id="style-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Brief description of this style's look and feel..."
                  className="flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  rows={2}
                  disabled={saving}
                />
              </div>

              {/* Category */}
              <div>
                <label htmlFor="style-category" className="mb-1 block text-sm font-medium text-foreground">
                  Category
                </label>
                <input
                  id="style-category"
                  type="text"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g., Brand, Minimal, Dark, Bold"
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  maxLength={50}
                  disabled={saving}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Optional category for organizing styles.
                </p>
              </div>

              {/* Style Content */}
              <div>
                <label className="mb-1 block text-sm font-medium text-foreground">
                  Style Content <span className="text-destructive">*</span>
                </label>
                <div className="overflow-hidden rounded-md border border-input">
                  <Editor
                    height="300px"
                    defaultLanguage="markdown"
                    value={styleContent}
                    onChange={(value) => setStyleContent(value || '')}
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
                  Define typography, colors, layout rules, and visual guidelines.
                  Include font sizes, color codes, spacing, and chart color palettes.
                </p>
              </div>
            </div>
          </div>

          {/* Footer - Fixed at bottom */}
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
              {saving ? 'Saving...' : mode === 'create' ? 'Create Style' : 'Save Changes'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
