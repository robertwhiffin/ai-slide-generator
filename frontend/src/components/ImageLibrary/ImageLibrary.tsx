import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FiExternalLink, FiX, FiTag, FiEdit2, FiCheck } from 'react-icons/fi';
import type { ImageAsset } from '../../types/image';
import { api } from '../../services/api';
import { DOCS_URLS } from '../../constants/docs';

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
  const [uploadProgress, setUploadProgress] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>(filterCategory || 'all');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploadTags, setUploadTags] = useState('');
  const [editingImageId, setEditingImageId] = useState<number | null>(null);
  const [editTagsValue, setEditTagsValue] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    images.forEach(img => img.tags?.forEach(t => tagSet.add(t)));
    return Array.from(tagSet).sort();
  }, [images]);

  const loadImages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { category?: string; query?: string; tags?: string[] } = {};
      if (selectedCategory !== 'all') params.category = selectedCategory;
      if (searchQuery.trim()) params.query = searchQuery.trim();
      if (selectedTags.length > 0) params.tags = selectedTags;
      const result = await api.listImages(params);
      setImages(result.images);
    } catch (err: any) {
      setError(err.message || 'Failed to load images');
    } finally {
      setLoading(false);
    }
  }, [selectedCategory, searchQuery, selectedTags]);

  useEffect(() => {
    loadImages();
  }, [loadImages]);

  const validateFile = (file: File): string | null => {
    if (!ALLOWED_TYPES.includes(file.type)) {
      return `${file.name}: Invalid file type (${file.type}). Allowed: PNG, JPEG, GIF, SVG`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `${file.name}: Too large (${(file.size / 1024 / 1024).toFixed(1)}MB, max 5MB)`;
    }
    return null;
  };

  const parseTagString = (raw: string): string[] =>
    raw.split(',').map(t => t.trim().toLowerCase()).filter(Boolean);

  const handleUploadFiles = async (files: File[]) => {
    const errors: string[] = [];
    const validFiles: File[] = [];
    for (const file of files) {
      const validationError = validateFile(file);
      if (validationError) {
        errors.push(validationError);
      } else {
        validFiles.push(file);
      }
    }

    if (validFiles.length === 0) {
      setError(errors.join('\n'));
      return;
    }

    setUploading(true);
    setError(null);

    const category = selectedCategory === 'all' ? 'content' : selectedCategory;
    const tags = parseTagString(uploadTags);
    let uploaded = 0;

    for (const file of validFiles) {
      setUploadProgress(`Uploading ${uploaded + 1} of ${validFiles.length}...`);
      try {
        await api.uploadImage(file, { category, tags: tags.length > 0 ? tags : undefined });
        uploaded++;
      } catch (err: any) {
        errors.push(`${file.name}: ${err.message || 'Upload failed'}`);
      }
    }

    setUploading(false);
    setUploadProgress('');

    if (errors.length > 0) {
      setError(errors.join('\n'));
    }

    if (uploaded > 0) {
      setUploadTags('');
      await loadImages();
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

  const handleSaveTags = async (imageId: number) => {
    try {
      const newTags = parseTagString(editTagsValue);
      const updated = await api.updateImage(imageId, { tags: newTags });
      setImages(prev => prev.map(img => img.id === imageId ? { ...img, tags: updated.tags } : img));
      setEditingImageId(null);
    } catch (err: any) {
      setError(err.message || 'Failed to update tags');
    }
  };

  const toggleTagFilter = (tag: string) => {
    setSelectedTags(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    );
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) handleUploadFiles(files);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length > 0) handleUploadFiles(files);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="space-y-4" data-testid="image-library">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Image Library</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {images.length} image{images.length !== 1 ? 's' : ''}
            {' · '}
            <a
              href={DOCS_URLS.uploadingImages}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800"
            >
              View guide <FiExternalLink size={12} />
            </a>
          </p>
        </div>
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

      {/* Tag Filter */}
      {allTags.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <FiTag className="text-gray-400" size={14} />
          {allTags.map(tag => (
            <button
              key={tag}
              onClick={() => toggleTagFilter(tag)}
              className={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
                selectedTags.includes(tag)
                  ? 'bg-blue-100 border-blue-300 text-blue-700'
                  : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'
              }`}
            >
              {tag}
            </button>
          ))}
          {selectedTags.length > 0 && (
            <button
              onClick={() => setSelectedTags([])}
              className="text-xs text-gray-400 hover:text-gray-600 underline"
            >
              clear
            </button>
          )}
        </div>
      )}

      {/* Upload Area */}
      {!readOnly && (
        <div className="space-y-2">
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
              multiple
              onChange={handleFileSelect}
              className="hidden"
            />
            {uploading ? (
              <p className="text-sm text-gray-500">{uploadProgress || 'Uploading...'}</p>
            ) : (
              <>
                <p className="text-sm text-gray-600">
                  Drop images here or <span className="text-blue-600 underline">browse</span>
                </p>
                <p className="text-xs text-gray-400 mt-1">PNG, JPEG, GIF, SVG (max 5MB each)</p>
              </>
            )}
          </div>
          <input
            type="text"
            placeholder="Tags for upload (comma-separated, e.g. logo, branding)"
            value={uploadTags}
            onChange={(e) => setUploadTags(e.target.value)}
            className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm flex items-start justify-between">
          <span className="whitespace-pre-line">{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700 ml-2 flex-shrink-0">
            &times;
          </button>
        </div>
      )}

      {/* Image Grid */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading images...</div>
      ) : images.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          {searchQuery || selectedTags.length > 0 ? 'No images match your filters' : 'No images uploaded yet'}
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
                ) : (
                  <span className="text-2xl text-gray-400">
                    {image.mime_type === 'image/svg+xml' ? 'SVG' : '?'}
                  </span>
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

                {/* Tags display / edit */}
                {editingImageId === image.id ? (
                  <div className="mt-1 flex gap-1" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="text"
                      value={editTagsValue}
                      onChange={(e) => setEditTagsValue(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleSaveTags(image.id); }}
                      className="flex-1 min-w-0 px-1.5 py-0.5 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                      autoFocus
                    />
                    <button
                      onClick={() => handleSaveTags(image.id)}
                      className="p-0.5 text-green-600 hover:text-green-800"
                      title="Save tags"
                    >
                      <FiCheck size={12} />
                    </button>
                    <button
                      onClick={() => setEditingImageId(null)}
                      className="p-0.5 text-gray-400 hover:text-gray-600"
                      title="Cancel"
                    >
                      <FiX size={12} />
                    </button>
                  </div>
                ) : (
                  <div className="mt-1 flex items-center gap-1 flex-wrap min-h-[18px]">
                    {image.tags && image.tags.length > 0 ? (
                      image.tags.map(tag => (
                        <span key={tag} className="px-1.5 py-0 text-[10px] bg-gray-100 text-gray-500 rounded-full">
                          {tag}
                        </span>
                      ))
                    ) : (
                      <span className="text-[10px] text-gray-300 italic">no tags</span>
                    )}
                    {!readOnly && !onSelect && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditTagsValue((image.tags || []).join(', '));
                          setEditingImageId(image.id);
                        }}
                        className="p-0.5 text-gray-300 hover:text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="Edit tags"
                      >
                        <FiEdit2 size={10} />
                      </button>
                    )}
                  </div>
                )}
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
