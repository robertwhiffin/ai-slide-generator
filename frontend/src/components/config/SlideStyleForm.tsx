/**
 * Slide Style form modal.
 *
 * Used for creating and editing slide styles.
 */

import React, { useState, useEffect, useRef } from 'react';
import { FiExternalLink } from 'react-icons/fi';
import Editor from '@monaco-editor/react';
import type { SlideStyle, SlideStyleCreate, SlideStyleUpdate } from '../../api/config';
import { ImagePicker } from '../ImageLibrary/ImagePicker';
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
        // Insert at cursor position
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

    // Fallback: append at end if no editor ref or cursor position
    setImageGuidelines(prev => prev + (prev ? '\n' : '') + textToInsert);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b bg-gray-50">
          <h2 className="text-xl font-semibold text-gray-900">
            {mode === 'create' ? 'Create Slide Style' : 'Edit Slide Style'}
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Define visual styling rules for slide generation (typography, colors, layout).
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-4">
            {/* Error Message */}
            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
                {error}
              </div>
            )}

            {/* Name */}
            <div>
              <label htmlFor="style-name" className="block text-sm font-medium text-gray-700 mb-1">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="style-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Databricks Brand"
                className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                maxLength={100}
                disabled={saving}
              />
            </div>

            {/* Description */}
            <div>
              <label htmlFor="style-description" className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                id="style-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this style's look and feel..."
                className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={2}
                disabled={saving}
              />
            </div>

            {/* Category */}
            <div>
              <label htmlFor="style-category" className="block text-sm font-medium text-gray-700 mb-1">
                Category
              </label>
              <input
                id="style-category"
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g., Brand, Minimal, Dark, Bold"
                className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                maxLength={50}
                disabled={saving}
              />
              <p className="text-xs text-gray-500 mt-1">
                Optional category for organizing styles.
              </p>
            </div>

            {/* Style Content */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Style Content <span className="text-red-500">*</span>
              </label>
              <div className="border border-gray-300 rounded overflow-hidden">
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
              <p className="text-xs text-gray-500 mt-1">
                Define typography, colors, layout rules, and visual guidelines.
                Include font sizes, color codes, spacing, and chart color palettes.
                {' '}
                <a
                  href={DOCS_URLS.customStylesCSS}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800"
                >
                  CSS reference <FiExternalLink size={10} />
                </a>
              </p>
            </div>

            {/* Image Guidelines */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-700">
                  Image Guidelines
                </label>
                <button
                  type="button"
                  onClick={() => setShowImagePicker(true)}
                  disabled={saving}
                  className="px-2.5 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                  title="Insert an image reference placeholder at cursor position"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <polyline points="21 15 16 10 5 21" />
                  </svg>
                  Insert Image Ref
                </button>
              </div>
              <div className="border border-gray-300 rounded overflow-hidden">
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
              <p className="text-xs text-gray-500 mt-1">
                Specify which images to include on slides (e.g. logos, backgrounds).
                Use "Insert Image Ref" to add image IDs. When set, the agent uses these images
                automatically without searching. Leave blank to skip image injection.
                {' '}
                <a
                  href={DOCS_URLS.imageGuidelines}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800"
                >
                  Image guidelines guide <FiExternalLink size={10} />
                </a>
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t bg-gray-50 flex justify-end gap-3">
            <button
              type="button"
              onClick={onCancel}
              disabled={saving}
              className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 rounded transition-colors disabled:bg-gray-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors disabled:bg-blue-300"
            >
              {saving ? 'Saving...' : mode === 'create' ? 'Create Style' : 'Save Changes'}
            </button>
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
