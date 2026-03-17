import React, { useState } from 'react';
import type { SlideDeck, Slide } from '../../types/slide';
import { VisualEditorPanel } from './VisualEditorPanel';
import { ImagePicker } from '../ImageLibrary/ImagePicker';
import { api } from '../../services/api';

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
  const [showImagePicker, setShowImagePicker] = useState(false);
  const [insertingImage, setInsertingImage] = useState(false);

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

  const handleImageSelect = async (image: { id: number; original_filename: string; description: string | null }) => {
    setInsertingImage(true);
    setError(null);
    try {
      const imageData = await api.getImageData(image.id);
      const alt = image.description || image.original_filename;
      const imgTag = `<img src="${imageData.data_uri}" alt="${alt}" style="max-width: 100%; height: auto;" />`;

      // Insert before the closing </section> tag if present, otherwise append
      if (editedHtml.includes('</section>')) {
        setEditedHtml(prev => prev.replace(/<\/section>\s*$/, `  ${imgTag}\n</section>`));
      } else {
        setEditedHtml(prev => prev + '\n' + imgTag);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load image data');
    } finally {
      setInsertingImage(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-[90%] h-[90%] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-semibold">Edit Slide</h2>
            <button
              type="button"
              onClick={() => setShowImagePicker(true)}
              disabled={isSaving || insertingImage}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
              title="Insert an image from the library"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              {insertingImage ? 'Inserting...' : 'Insert Image'}
            </button>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-gray-500 hover:text-gray-700"
            disabled={isSaving}
            aria-label="Close"
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

      {/* Image Picker Modal */}
      <ImagePicker
        isOpen={showImagePicker}
        onClose={() => setShowImagePicker(false)}
        onSelect={handleImageSelect}
      />
    </div>
  );
};
