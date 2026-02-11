import React, { useState, useRef, useLayoutEffect } from 'react';
import { PromptEditorModal } from './PromptEditorModal';
import type { ImageAsset } from '../../types/image';
import { api } from '../../services/api';

interface ChatInputProps {
  onSend: (message: string, imageIds?: number[]) => void;
  disabled: boolean;
  placeholder?: string;
  badge?: React.ReactNode;
}

const MIN_ROWS = 2;
const MAX_ROWS = 10;
const LINE_HEIGHT = 24; // Approximate line height in pixels
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  disabled,
  placeholder,
  badge,
}) => {
  const [message, setMessage] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [attachedImages, setAttachedImages] = useState<ImageAsset[]>([]);
  const [saveToLibrary, setSaveToLibrary] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Use useLayoutEffect to avoid visual flicker and prevent infinite loops
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Reset height to auto to measure scrollHeight
    textarea.style.height = 'auto';

    const minHeight = MIN_ROWS * LINE_HEIGHT;
    const maxHeight = MAX_ROWS * LINE_HEIGHT;

    // Calculate new height based on content
    const scrollHeight = textarea.scrollHeight;
    const newHeight = Math.min(Math.max(scrollHeight, minHeight), maxHeight);

    textarea.style.height = `${newHeight}px`;

    // Enable scrolling if content exceeds max height
    textarea.style.overflowY = scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [message]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !disabled) {
      const imageIds = attachedImages.length > 0
        ? attachedImages.map(img => img.id)
        : undefined;
      onSend(message.trim(), imageIds);
      setMessage('');
      setAttachedImages([]);
      setUploadError(null);
    }
  };

  const handleModalSave = (text: string) => {
    setMessage(text);
    setIsModalOpen(false);
  };

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    for (const item of Array.from(items)) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;

        if (file.size > MAX_FILE_SIZE) {
          setUploadError('Image too large (max 5MB)');
          continue;
        }

        setUploading(true);
        setUploadError(null);
        try {
          const uploaded = await api.uploadImage(file, {
            category: saveToLibrary ? 'content' : undefined,
            saveToLibrary: saveToLibrary,
          });
          setAttachedImages(prev => [...prev, uploaded]);
        } catch {
          setUploadError('Failed to upload pasted image');
        } finally {
          setUploading(false);
        }
      }
    }
  };

  const removeAttachment = (imageId: number) => {
    setAttachedImages(prev => prev.filter(img => img.id !== imageId));
  };

  const lineCount = message.split('\n').length;
  const charCount = message.length;

  return (
    <>
      <form onSubmit={handleSubmit} className="p-4 bg-white border-t">
        {/* Attachment Preview */}
        {attachedImages.length > 0 && (
          <div className="flex items-center gap-2 mb-2 p-2 bg-gray-50 rounded-lg">
            {attachedImages.map(img => (
              <div key={img.id} className="relative group">
                {img.thumbnail_base64 ? (
                  <img
                    src={img.thumbnail_base64}
                    alt={img.original_filename}
                    className="w-12 h-12 object-cover rounded border border-gray-200"
                  />
                ) : (
                  <div className="w-12 h-12 bg-gray-200 rounded flex items-center justify-center text-xs text-gray-500">
                    IMG
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => removeAttachment(img.id)}
                  className="absolute -top-1 -right-1 bg-red-500 text-white rounded-full w-4 h-4 text-xs leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  &times;
                </button>
              </div>
            ))}
            <label className="flex items-center gap-1 text-xs text-gray-500 ml-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={saveToLibrary}
                onChange={(e) => setSaveToLibrary(e.target.checked)}
                className="rounded border-gray-300"
              />
              Save to library
            </label>
          </div>
        )}

        {/* Upload Error */}
        {uploadError && (
          <div className="mb-2 p-2 bg-red-50 text-red-700 rounded text-xs flex items-center justify-between">
            <span>{uploadError}</span>
            <button type="button" onClick={() => setUploadError(null)} className="text-red-500 hover:text-red-700 ml-2">
              &times;
            </button>
          </div>
        )}

        <div className="flex items-end space-x-2">
          <div className="flex-1">
            {badge && <div className="mb-2">{badge}</div>}
            <div className="relative">
              <textarea
                ref={textareaRef}
                data-testid="chat-input"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onPaste={handlePaste}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit(e);
                  }
                }}
                placeholder={uploading ? 'Uploading image...' : (placeholder ?? 'Ask me to create slides...')}
                disabled={disabled}
                className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none transition-all duration-150"
                style={{
                  minHeight: `${MIN_ROWS * LINE_HEIGHT}px`,
                  maxHeight: `${MAX_ROWS * LINE_HEIGHT}px`,
                  lineHeight: `${LINE_HEIGHT}px`,
                }}
              />
              {/* Expand button */}
              <button
                type="button"
                onClick={() => setIsModalOpen(true)}
                disabled={disabled}
                className="absolute right-2 top-2 p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors disabled:opacity-50"
                title="Expand editor (for long prompts)"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="15 3 21 3 21 9" />
                  <polyline points="9 21 3 21 3 15" />
                  <line x1="21" y1="3" x2="14" y2="10" />
                  <line x1="3" y1="21" x2="10" y2="14" />
                </svg>
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={disabled || !message.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </div>

        <div className="mt-1 flex items-center justify-between text-xs text-gray-500">
          <span>Press Enter to send, Shift+Enter for new line</span>
          {message.length > 0 && (
            <span className="text-gray-400">
              {lineCount} {lineCount === 1 ? 'line' : 'lines'} · {charCount} chars
            </span>
          )}
        </div>
      </form>

      {isModalOpen && (
        <PromptEditorModal
          initialText={message}
          placeholder={placeholder ?? 'Ask me to create slides...'}
          onSave={handleModalSave}
          onCancel={() => setIsModalOpen(false)}
          onSend={(text) => {
            if (text.trim() && !disabled) {
              const imageIds = attachedImages.length > 0
                ? attachedImages.map(img => img.id)
                : undefined;
              onSend(text.trim(), imageIds);
              setMessage('');
              setAttachedImages([]);
              setIsModalOpen(false);
            }
          }}
          disabled={disabled}
        />
      )}
    </>
  );
};
