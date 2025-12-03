import React, { useEffect, useRef, useState } from 'react';
import type { Message } from '../../types/message';
import type { ReplacementInfo, SlideDeck } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { api } from '../../services/api';
import { getRotatingLoadingMessage } from '../../utils/loadingMessages';
import { SelectionBadge } from './SelectionBadge';
import { ReplacementFeedback } from './ReplacementFeedback';
import { ErrorDisplay } from './ErrorDisplay';
import { LoadingIndicator } from './LoadingIndicator';
import { useSelection } from '../../contexts/SelectionContext';
import { useSession } from '../../contexts/SessionContext';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';

interface ChatPanelProps {
  rawHtml: string | null;
  onSlidesGenerated: (slideDeck: SlideDeck, rawHtml: string | null) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  rawHtml,
  onSlidesGenerated,
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [lastReplacement, setLastReplacement] = useState<ReplacementInfo | null>(
    null,
  );
  const messageIndexRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const {
    selectedIndices,
    selectedSlides,
    hasSelection,
    clearSelection,
  } = useSelection();
  const { sessionId, isInitializing, error: sessionError } = useSession();

  useKeyboardShortcuts();

  // Show session error
  useEffect(() => {
    if (sessionError) {
      setError(sessionError);
    }
  }, [sessionError]);

  const stopLoadingMessages = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setLoadingMessage('');
  };

  const handleSendMessage = async (content: string) => {
    const trimmedContent = content.trim();
    if (!trimmedContent) {
      return;
    }

    if (!sessionId) {
      setError('Session not initialized. Please refresh the page.');
      return;
    }

    setIsLoading(true);
    setError(null);
    setLastReplacement(null);

    setMessages(prev => [
      ...prev,
      {
        role: 'user',
        content: trimmedContent,
        timestamp: new Date().toISOString(),
      },
    ]);

    messageIndexRef.current = 0;
    setLoadingMessage(getRotatingLoadingMessage(0));
    intervalRef.current = setInterval(() => {
      messageIndexRef.current += 1;
      setLoadingMessage(getRotatingLoadingMessage(messageIndexRef.current));
    }, 3000);

    const slideContext =
      hasSelection && selectedIndices.length > 0
        ? {
            indices: selectedIndices,
            slide_htmls: selectedSlides.map(slide => slide.html),
          }
        : undefined;

    try {
      const response = await api.sendMessage({
        sessionId,
        message: trimmedContent,
        slideContext,
      });

      stopLoadingMessages();

      const newMessages = response.messages.filter(m => m.role !== 'user');
      setMessages(prev => [...prev, ...newMessages]);

      const nextRawHtml = response.raw_html ?? rawHtml ?? null;

      if (response.slide_deck) {
        onSlidesGenerated(response.slide_deck, nextRawHtml);
        clearSelection();
      }

      if (response.replacement_info && slideContext) {
        if (response.slide_deck === undefined) {
          console.warn('Replacement info received without slide deck; skipping local merge.');
        }
        setLastReplacement(response.replacement_info);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      stopLoadingMessages();
      setIsLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  return (
    <div className="flex flex-col h-full bg-gray-50">
      <div className="p-4 border-b bg-white flex items-center justify-between">
        <h2 className="text-lg font-semibold">Chat</h2>
        {hasSelection && (
          <span className="text-sm text-blue-600 font-medium">
            {selectedIndices.length} slide
            {selectedIndices.length === 1 ? '' : 's'} selected
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} isLoading={isLoading} />
      </div>

      {error && (
        <ErrorDisplay error={error} onDismiss={() => setError(null)} />
      )}

      {loadingMessage && <LoadingIndicator message={loadingMessage} />}

      <ChatInput
        onSend={handleSendMessage}
        disabled={isLoading || isInitializing || !sessionId}
        placeholder={
          isInitializing
            ? 'Initializing session...'
            : hasSelection
            ? 'Describe changes to selected slides...'
            : 'Ask to generate or modify slides...'
        }
        badge={
          hasSelection ? (
            <SelectionBadge
              selectedIndices={selectedIndices}
              onClear={clearSelection}
            />
          ) : undefined
        }
      />

      {lastReplacement && (
        <div className="px-4 pb-4">
          <ReplacementFeedback replacementInfo={lastReplacement} />
        </div>
      )}
    </div>
  );
};
