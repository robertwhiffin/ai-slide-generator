import React, { useEffect, useRef, useState } from 'react';
import type { Message } from '../../types/message';
import type { ReplacementInfo, SlideDeck } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { api, type StreamEvent } from '../../services/api';
import { getRotatingLoadingMessage } from '../../utils/loadingMessages';
import { SelectionBadge } from './SelectionBadge';
import { ReplacementFeedback } from './ReplacementFeedback';
import { ErrorDisplay } from './ErrorDisplay';
import { LoadingIndicator } from './LoadingIndicator';
import { useSelection } from '../../contexts/SelectionContext';
import { useSession } from '../../contexts/SessionContext';
import { useGeneration } from '../../contexts/GenerationContext';
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
  const cancelStreamRef = useRef<(() => void) | null>(null);
  const {
    selectedIndices,
    selectedSlides,
    hasSelection,
    clearSelection,
  } = useSelection();
  const { sessionId, isInitializing, error: sessionError } = useSession();
  const { setIsGenerating } = useGeneration();

  useKeyboardShortcuts();

  // Show session error
  useEffect(() => {
    if (sessionError) {
      setError(sessionError);
    }
  }, [sessionError]);

  // Load messages when session changes (for restored sessions)
  useEffect(() => {
    if (!sessionId) return;

    const loadSessionMessages = async () => {
      try {
        const session = await api.getSession(sessionId);
        if (session.messages && session.messages.length > 0) {
          // Convert database messages to UI Message format
          const uiMessages: Message[] = session.messages.map(msg => ({
            role: msg.role as 'user' | 'assistant' | 'tool',
            content: msg.content,
            timestamp: msg.created_at,
            tool_call: msg.metadata?.tool_name ? {
              name: msg.metadata.tool_name,
              arguments: msg.metadata.tool_input || {},
            } : undefined,
          }));
          setMessages(uiMessages);
        } else {
          setMessages([]);
        }
      } catch (err: any) {
        // Session might not exist yet (new session with local UUID), which is fine
        // 404 is expected for new sessions that haven't sent their first message
        if (err?.status !== 404) {
          console.warn('Could not load session messages:', err);
        }
        setMessages([]);
      }
    };

    loadSessionMessages();
  }, [sessionId]);

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
    setIsGenerating(true);
    setError(null);
    setLastReplacement(null);

    // Add user message immediately
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

    // Handle streaming events
    const handleStreamEvent = (event: StreamEvent) => {
      switch (event.type) {
        case 'assistant':
          if (event.content) {
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                content: event.content!,
                timestamp: new Date().toISOString(),
              },
            ]);
          }
          break;

        case 'tool_call':
          if (event.tool_name) {
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                content: `Using tool: ${event.tool_name}`,
                timestamp: new Date().toISOString(),
                tool_call: {
                  name: event.tool_name!,
                  arguments: event.tool_input || {},
                },
              },
            ]);
            // Update loading message to show tool being used
            setLoadingMessage(`Querying ${event.tool_name}...`);
          }
          break;

        case 'tool_result':
          if (event.tool_output) {
            setMessages(prev => [
              ...prev,
              {
                role: 'tool',
                content: event.tool_output!,
                timestamp: new Date().toISOString(),
                tool_call_id: event.tool_name,
              },
            ]);
          }
          break;

        case 'error':
          setError(event.error || 'An error occurred');
          stopLoadingMessages();
          setIsLoading(false);
          setIsGenerating(false);
          break;

        case 'complete':
          stopLoadingMessages();
          setIsLoading(false);
          setIsGenerating(false);

          const nextRawHtml = event.raw_html ?? rawHtml ?? null;

          if (event.slides) {
            onSlidesGenerated(event.slides, nextRawHtml);
            clearSelection();
          }

          if (event.replacement_info && slideContext) {
            setLastReplacement(event.replacement_info);
          }
          break;
      }
    };

    // Start streaming (automatically uses SSE or polling based on environment)
    cancelStreamRef.current = api.sendChatMessage(
      sessionId,
      trimmedContent,
      slideContext,
      handleStreamEvent,
      (err) => {
        console.error('Chat error:', err);
        setError(err.message || 'Failed to send message');
        stopLoadingMessages();
        setIsLoading(false);
        setIsGenerating(false);
      }
    );
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      // Cancel any in-flight stream
      if (cancelStreamRef.current) {
        cancelStreamRef.current();
      }
      // Reset generation state on unmount
      setIsGenerating(false);
    };
  }, [setIsGenerating]);

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
