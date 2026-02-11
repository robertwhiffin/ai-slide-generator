import React from 'react';
import type { ImageAsset } from '../../types/image';
import { ImageLibrary } from './ImageLibrary';

interface ImagePickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (image: ImageAsset) => void;
  filterCategory?: string;
}

export const ImagePicker: React.FC<ImagePickerProps> = ({
  isOpen,
  onClose,
  onSelect,
  filterCategory,
}) => {
  if (!isOpen) return null;

  const handleSelect = (image: ImageAsset) => {
    onSelect(image);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black bg-opacity-50"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[80vh] flex flex-col mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-gray-900">Select Image</h3>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <ImageLibrary
            onSelect={handleSelect}
            readOnly={false}
            filterCategory={filterCategory}
          />
        </div>
      </div>
    </div>
  );
};
