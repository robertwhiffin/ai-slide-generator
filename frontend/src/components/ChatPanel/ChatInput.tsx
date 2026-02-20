import React, { useState, useRef, useLayoutEffect, useCallback } from 'react';
import { Send, Maximize2, ImagePlus, X } from 'lucide-react';
import { Button } from '@/ui/button';
import { PromptEditorModal } from './PromptEditorModal';
import { api } from '../../services/api';

interface ChatInputProps {
  onSend: (message: string, imageIds?: number[]) => void;
  disabled: boolean;
  placeholder?: string;
  badge?: React.ReactNode;
}

interface AttachedImage {
  id: number;
  previewUrl?: string;
}

const MIN_ROWS = 2;
const MAX_ROWS = 10;
const LINE_HEIGHT = 24; // Approximate line height in pixels

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  disabled,
  placeholder,
  badge,
}) => {
  const [message, setMessage] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const addUploadedImage = useCallback((id: number, previewUrl?: string) => {
    setAttachedImages((prev) => (prev.some((a) => a.id === id) ? prev : [...prev, { id, previewUrl }]));
  }, []);

  const removeAttachment = useCallback((id: number) => {
    setAttachedImages((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const handlePaste = useCallback(
    async (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items || disabled || uploading) return;
      const file = Array.from(items).find((item) => item.kind === 'file' && item.type.startsWith('image/'));
      if (!file) return;
      e.preventDefault();
      const f = file.getAsFile();
      if (!f) return;
      setUploading(true);
      try {
        const asset = await api.uploadImage(f, { saveToLibrary: false });
        const previewUrl = asset.thumbnail_base64
          ? `data:${asset.mime_type};base64,${asset.thumbnail_base64}`
          : undefined;
        addUploadedImage(asset.id, previewUrl);
      } catch (err) {
        console.warn('Paste image upload failed:', err);
      } finally {
        setUploading(false);
      }
    },
    [disabled, uploading, addUploadedImage]
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files?.length || disabled || uploading) return;
      setUploading(true);
      try {
        for (const file of Array.from(files)) {
          if (!file.type.startsWith('image/')) continue;
          const asset = await api.uploadImage(file, { saveToLibrary: false });
          const previewUrl = asset.thumbnail_base64
            ? `data:${asset.mime_type};base64,${asset.thumbnail_base64}`
            : undefined;
          addUploadedImage(asset.id, previewUrl);
        }
      } catch (err) {
        console.warn('Image upload failed:', err);
      } finally {
        setUploading(false);
      }
      e.target.value = '';
    },
    [disabled, uploading, addUploadedImage]
  );

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
    const text = message.trim();
    if (!text && attachedImages.length === 0) return;
    if (disabled) return;
    const imageIds = attachedImages.length > 0 ? attachedImages.map((a) => a.id) : undefined;
    onSend(text || 'Use these images', imageIds);
    setMessage('');
    setAttachedImages([]);
  };

  const handleModalSave = (text: string) => {
    setMessage(text);
    setIsModalOpen(false);
  };

  const lineCount = message.split('\n').length;
  const charCount = message.length;

  const canSend = message.trim() || attachedImages.length > 0;

  return (
    <>
      <form onSubmit={handleSubmit} className="border-t border-border bg-card px-4 py-3">
        {badge && <div className="mb-2">{badge}</div>}
        {attachedImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachedImages.map(({ id, previewUrl }) => (
              <div
                key={id}
                className="relative h-14 w-14 rounded-lg border border-border bg-muted overflow-hidden"
              >
                {previewUrl ? (
                  <img src={previewUrl} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="h-full w-full flex items-center justify-center text-muted-foreground text-xs">#{id}</div>
                )}
                <button
                  type="button"
                  onClick={() => removeAttachment(id)}
                  className="absolute top-0.5 right-0.5 rounded-full bg-background/80 p-0.5 hover:bg-destructive hover:text-destructive-foreground"
                  aria-label="Remove"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="relative flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onPaste={handlePaste}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder={placeholder ?? 'Ask me to create slides...'}
              disabled={disabled}
              data-testid="chat-input"
              className="w-full px-3 py-2 pr-20 border border-input bg-background rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0 resize-none transition-all duration-150 text-sm"
              style={{
                minHeight: `${MIN_ROWS * LINE_HEIGHT}px`,
                maxHeight: `${MAX_ROWS * LINE_HEIGHT}px`,
                lineHeight: `${LINE_HEIGHT}px`,
              }}
            />
            <div className="absolute right-2 top-2 flex gap-1">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={handleFileSelect}
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled || uploading}
                className="h-7 w-7"
                title="Attach image"
              >
                <ImagePlus className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => setIsModalOpen(true)}
                disabled={disabled}
                className="h-7 w-7"
                title="Expand editor (for long prompts)"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </Button>
              <Button
                type="submit"
                size="icon"
                disabled={disabled || !canSend}
                className="h-7 w-7"
                title="Send message (Enter)"
                aria-label="Send"
              >
                <Send className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-1.5 flex items-center justify-between text-xs text-muted-foreground">
          <span>Press Enter to send, Shift+Enter for new line</span>
          {message.length > 0 && (
            <span>
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
              onSend(text.trim(), undefined);
              setMessage('');
              setIsModalOpen(false);
            }
          }}
          disabled={disabled}
        />
      )}
    </>
  );
};
