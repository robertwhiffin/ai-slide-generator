/**
 * Slide Style form modal.
 *
 * Used for creating and editing slide styles.
 */

import React, { useState, useEffect, useRef } from 'react';
import { AlertCircle, ExternalLink, ImageIcon } from 'lucide-react';
import Editor from '@monaco-editor/react';
import { Button } from '@/ui/button';
import type { SlideStyle, SlideStyleCreate, SlideStyleUpdate } from '../../api/config';
import { ImagePicker } from '../ImageLibrary/ImagePicker';
import { ExpandableEditor } from './ExpandableEditor';
import { DOCS_URLS } from '../../constants/docs';

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
  const [imageGuidelines, setImageGuidelines] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showImagePicker, setShowImagePicker] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const imageGuidelinesEditorRef = useRef<any>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving && !showImagePicker) onCancel();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, saving, showImagePicker, onCancel]);

  // Reset form when opening
  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && style) {
        setName(style.name);
        setDescription(style.description || '');
        setCategory(style.category || '');
        setStyleContent(style.style_content);
        setImageGuidelines(style.image_guidelines || '');
      } else {
        setName('');
        setDescription('');
        setCategory('');
        setStyleContent('');
        setImageGuidelines('');
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
        image_guidelines: imageGuidelines.trim() || null,
      };
      await onSubmit(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleInsertImageRef = (image: { id: number; original_filename: string }) => {
    const textToInsert = `{{image:${image.id}}}  /* ${image.original_filename} */`;

    const editor = imageGuidelinesEditorRef.current;
    if (editor) {
      const position = editor.getPosition();
      if (position) {
        editor.executeEdits('insert-image-ref', [{
          range: {
            startLineNumber: position.lineNumber,
            startColumn: position.column,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
          },
          text: textToInsert,
        }]);
        editor.focus();
        return;
      }
    }

    setImageGuidelines(prev => prev + (prev ? '\n' : '') + textToInsert);
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
                <ExpandableEditor
                  value={styleContent}
                  onChange={setStyleContent}
                  readOnly={saving}
                  modalTitle="Style Content"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Define typography, colors, layout rules, and visual guidelines.
                  Include font sizes, color codes, spacing, and chart color palettes.
                  {' '}
                  <a
                    href={DOCS_URLS.customStylesCSS}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    CSS reference <ExternalLink className="size-2.5" />
                  </a>
                </p>
              </div>

              {/* Image Guidelines */}
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="block text-sm font-medium text-foreground">
                    Image Guidelines
                  </label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setShowImagePicker(true)}
                    disabled={saving}
                    className="h-7 gap-1 text-xs"
                  >
                    <ImageIcon className="size-3" />
                    Insert Image Ref
                  </Button>
                </div>
                <div className="overflow-hidden rounded-md border border-input">
                  <Editor
                    height="150px"
                    defaultLanguage="markdown"
                    value={imageGuidelines}
                    onChange={(value) => setImageGuidelines(value || '')}
                    onMount={(editor) => { imageGuidelinesEditorRef.current = editor; }}
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
                  Specify which images to include on slides (e.g. logos, backgrounds).
                  Use &quot;Insert Image Ref&quot; to add image IDs. When set, the agent uses these images
                  automatically without searching. Leave blank to skip image injection.
                  {' '}
                  <a
                    href={DOCS_URLS.imageGuidelines}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    Image guidelines guide <ExternalLink className="size-2.5" />
                  </a>
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

      {/* Image Picker for inserting image references */}
      <ImagePicker
        isOpen={showImagePicker}
        onClose={() => setShowImagePicker(false)}
        onSelect={(image) => {
          handleInsertImageRef(image);
          setShowImagePicker(false);
        }}
      />
    </div>
  );
};
