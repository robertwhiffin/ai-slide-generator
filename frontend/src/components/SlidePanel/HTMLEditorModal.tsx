import React, { useState } from 'react';
import type { SlideDeck, Slide } from '../../types/slide';
import { VisualEditorPanel } from './VisualEditorPanel';

interface HTMLEditorModalProps {
  html: string;
  slideDeck: SlideDeck;
  slide: Slide;
  onSave: (html: string) => Promise<void>;
  onCancel: () => void;
}

export const HTMLEditorModal: React.FC<HTMLEditorModalProps> = ({
  html,
  slideDeck,
  slide,
  onSave,
  onCancel,
}) => {
  const [editedHtml, setEditedHtml] = useState(html);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setError(null);
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
          <h2 className="text-xl font-semibold">Edit Slide</h2>
          <button
            onClick={onCancel}
            className="text-gray-500 hover:text-gray-700"
            disabled={isSaving}
          >
            ✕
          </button>
        </div>

        {/* Visual Editor */}
        <div className="flex-1 overflow-hidden">
          <VisualEditorPanel
            html={editedHtml}
            slideDeck={slideDeck}
            slide={slide}
            onChange={setEditedHtml}
          />
        </div>

        {/* Error Display */}
        {error && (
          <div className="px-6 py-3 bg-red-50 border-t border-red-200">
            <p className="text-sm text-red-600 whitespace-pre-line">{error}</p>
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-4 border-t flex items-center justify-end space-x-3">
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
  );
};
