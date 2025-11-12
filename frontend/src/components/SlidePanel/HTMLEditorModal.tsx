import React, { useState } from 'react';
import Editor from '@monaco-editor/react';

interface HTMLEditorModalProps {
  html: string;
  onSave: (html: string) => Promise<void>;
  onCancel: () => void;
}

export const HTMLEditorModal: React.FC<HTMLEditorModalProps> = ({
  html,
  onSave,
  onCancel,
}) => {
  const [editedHtml, setEditedHtml] = useState(html);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateHTML = (html: string): string | null => {
    // Simple check: does any div have "slide" as a complete word in its class attribute?
    // \b ensures word boundary, so "slide" matches but "slide-content" doesn't
    const hasSlideClass = /<div[^>]*class=["'][^"']*\bslide\b[^"']*["']/i.test(html);
    
    if (!hasSlideClass) {
      return `HTML must contain a <div> with "slide" as one of the classes.

Valid examples:
  • <div class="slide">
  • <div class="slide title">
  • <div class="title slide">

Invalid examples:
  • <div class="title"> (missing "slide")
  • <div class="title-slide"> ("title-slide" is one class, not "slide")`;
    }

    // Basic HTML validation (check for balanced tags)
    const openDivs = (html.match(/<div/g) || []).length;
    const closeDivs = (html.match(/<\/div>/g) || []).length;
    
    if (openDivs !== closeDivs) {
      return 'Unbalanced <div> tags detected';
    }

    return null;
  };

  const handleSave = async () => {
    setError(null);

    // Validate
    const validationError = validateHTML(editedHtml);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSaving(true);
    try {
      await onSave(editedHtml);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-[90%] h-[90%] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <h2 className="text-xl font-semibold">Edit Slide HTML</h2>
          <button
            onClick={onCancel}
            className="text-gray-500 hover:text-gray-700"
            disabled={isSaving}
          >
            ✕
          </button>
        </div>

        {/* Editor */}
        <div className="flex-1 overflow-hidden">
          <Editor
            height="100%"
            defaultLanguage="html"
            value={editedHtml}
            onChange={(value) => setEditedHtml(value || '')}
            theme="vs-light"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              wordWrap: 'on',
              formatOnPaste: true,
              formatOnType: true,
            }}
          />
        </div>

        {/* Error Display */}
        {error && (
          <div className="px-6 py-3 bg-red-50 border-t border-red-200">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-4 border-t flex items-center justify-between">
          <div className="text-sm text-gray-500">
            Div must include "slide" as one of its classes (e.g., <code>class="slide"</code> or <code>class="slide title"</code>)
          </div>
          
          <div className="flex space-x-3">
            <button
              onClick={onCancel}
              disabled={isSaving}
              className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

