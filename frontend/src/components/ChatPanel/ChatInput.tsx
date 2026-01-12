import React, { useState, useRef, useLayoutEffect } from 'react';
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
      <form onSubmit={handleSubmit} className="p-4 bg-white border-t">
        <div className="flex items-end space-x-2">
          <div className="flex-1">
            {badge && <div className="mb-2">{badge}</div>}
            <div className="relative">
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
