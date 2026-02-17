import React, { useState, useRef, useLayoutEffect } from 'react';
import { Send, Maximize2 } from 'lucide-react';
import { Button } from '@/ui/button';
import { PromptEditorModal } from './PromptEditorModal';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
  placeholder?: string;
  badge?: React.ReactNode;
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
      onSend(message.trim());
      setMessage('');
    }
  };

  const handleModalSave = (text: string) => {
    setMessage(text);
    setIsModalOpen(false);
  };

  const lineCount = message.split('\n').length;
  const charCount = message.length;

  return (
    <>
      <form onSubmit={handleSubmit} className="border-t border-border bg-card px-4 py-3">
        {badge && <div className="mb-2">{badge}</div>}
        <div className="relative flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder={placeholder ?? 'Ask me to create slides...'}
              disabled={disabled}
              className="w-full px-3 py-2 pr-20 border border-input bg-background rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0 resize-none transition-all duration-150 text-sm"
              style={{
                minHeight: `${MIN_ROWS * LINE_HEIGHT}px`,
                maxHeight: `${MAX_ROWS * LINE_HEIGHT}px`,
                lineHeight: `${LINE_HEIGHT}px`,
              }}
            />
            <div className="absolute right-2 top-2 flex gap-1">
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
                disabled={disabled || !message.trim()}
                className="h-7 w-7"
                title="Send message (Enter)"
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
              onSend(text.trim());
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
