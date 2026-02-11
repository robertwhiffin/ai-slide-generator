import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { ImageAsset } from '../../types/image';
import { api } from '../../services/api';

const MAX_FILE_SIZE = 5 * 1024 * 1024;
const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/svg+xml'];
const CATEGORIES = ['all', 'branding', 'content', 'background'] as const;

interface ImageLibraryProps {
  /** If provided, clicking an image calls this instead of showing details */
  onSelect?: (image: ImageAsset) => void;
  /** Hide upload/delete controls */
  readOnly?: boolean;
  /** Pre-filter by category */
  filterCategory?: string;
}

export const ImageLibrary: React.FC<ImageLibraryProps> = ({
  onSelect,
  readOnly = false,
  filterCategory,
}) => {
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>(filterCategory || 'all');
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadImages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { category?: string; query?: string } = {};
      if (selectedCategory !== 'all') params.category = selectedCategory;
      if (searchQuery.trim()) params.query = searchQuery.trim();
      const result = await api.listImages(params);
      setImages(result.images);
    } catch (err: any) {
      setError(err.message || 'Failed to load images');
    } finally {
      setLoading(false);
    }
  }, [selectedCategory, searchQuery]);

  useEffect(() => {
    loadImages();
  }, [loadImages]);

  const validateFile = (file: File): string | null => {
    if (!ALLOWED_TYPES.includes(file.type)) {
      return `Invalid file type: ${file.type}. Allowed: PNG, JPEG, GIF, SVG`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File too large: ${(file.size / 1024 / 1024).toFixed(1)}MB (max 5MB)`;
    }
    return null;
  };

  const handleUpload = async (file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setUploading(true);
    setError(null);
    try {
      await api.uploadImage(file, {
        category: selectedCategory === 'all' ? 'content' : selectedCategory,
      });
      await loadImages();
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (imageId: number) => {
    try {
      await api.deleteImage(imageId);
      setImages(prev => prev.filter(img => img.id !== imageId));
    } catch (err: any) {
      setError(err.message || 'Delete failed');
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">Image Library</h2>
        <span className="text-sm text-gray-500">{images.length} image{images.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Search + Category Filter */}
      <div className="flex gap-3">
        <input
          type="text"
          placeholder="Search images..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {!filterCategory && (
          <div className="flex gap-1">
            {CATEGORIES.map(cat => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-3 py-2 text-sm rounded-lg transition-colors capitalize ${
                  selectedCategory === cat
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Upload Area */}
      {!readOnly && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${
            dragOver
              ? 'border-blue-500 bg-blue-50'
              : 'border-gray-300 hover:border-gray-400'
          } ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/svg+xml"
            onChange={handleFileSelect}
            className="hidden"
          />
          {uploading ? (
            <p className="text-sm text-gray-500">Uploading...</p>
          ) : (
            <>
              <p className="text-sm text-gray-600">
                Drop image here or <span className="text-blue-600 underline">browse</span>
              </p>
              <p className="text-xs text-gray-400 mt-1">PNG, JPEG, GIF, SVG (max 5MB)</p>
            </>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700 ml-2">
            &times;
          </button>
        </div>
      )}

      {/* Image Grid */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading images...</div>
      ) : images.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          {searchQuery ? 'No images match your search' : 'No images uploaded yet'}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {images.map(image => (
            <div
              key={image.id}
              className={`group relative rounded-lg border border-gray-200 overflow-hidden bg-white hover:shadow-md transition-shadow ${
                onSelect ? 'cursor-pointer' : ''
              }`}
              onClick={() => onSelect?.(image)}
            >
              {/* Thumbnail */}
              <div className="aspect-square bg-gray-100 flex items-center justify-center">
                {image.thumbnail_base64 ? (
                  <img
                    src={image.thumbnail_base64}
                    alt={image.description || image.original_filename}
                    className="max-w-full max-h-full object-contain"
                  />
                ) : image.mime_type === 'image/svg+xml' ? (
                  <span className="text-2xl text-gray-400">SVG</span>
                ) : (
                  <span className="text-2xl text-gray-400">?</span>
                )}
              </div>

              {/* Info */}
              <div className="p-2">
                <p className="text-xs text-gray-700 truncate" title={image.original_filename}>
                  {image.original_filename}
                </p>
                <p className="text-xs text-gray-400">
                  {formatSize(image.size_bytes)}
                  {image.category && <span className="ml-1 capitalize">· {image.category}</span>}
                </p>
              </div>

              {/* Delete button (hover) */}
              {!readOnly && !onSelect && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(image.id);
                  }}
                  className="absolute top-1 right-1 p-1 bg-red-500 text-white rounded opacity-0 group-hover:opacity-100 transition-opacity text-xs"
                  title="Delete image"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
