import React, { useState, useEffect, useRef } from 'react';
import type { Message } from '../../types/message';
import type { SlideDeck } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { api } from '../../services/api';
import { getRotatingLoadingMessage } from '../../utils/loadingMessages';

interface ChatPanelProps {
  onSlidesGenerated: (slideDeck: SlideDeck, rawHtml: string | null) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ onSlidesGenerated }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const messageIndexRef = useRef(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const handleSendMessage = async (content: string, maxSlides: number) => {
    setIsLoading(true);
    setError(null);

    // 1. Show user message immediately
    setMessages(prev => [...prev, {
      role: 'user',
      content: content,
      timestamp: new Date().toISOString(),
    }]);

    // 2. Start rotating through funny messages
    messageIndexRef.current = 0;
    setLoadingMessage(getRotatingLoadingMessage(0));
    
    intervalRef.current = setInterval(() => {
      messageIndexRef.current += 1;
      setLoadingMessage(getRotatingLoadingMessage(messageIndexRef.current));
    }, 3000); // Change message every 3 seconds

    try {
      // 3. Call API (blocking, but user sees funny messages)
      const response = await api.sendMessage(content, maxSlides);
      
      // 4. Stop rotating messages
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      
      // 5. Add real messages (skip user message as we already showed it)
      const newMessages = response.messages.filter(m => m.role !== 'user');
      setMessages(prev => [...prev, ...newMessages]);
      
      // 6. Update slides and raw HTML
      if (response.slide_deck) {
        onSlidesGenerated(response.slide_deck, response.raw_html);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      setIsLoading(false);
      setLoadingMessage('');
    }
  };

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="p-4 border-b bg-white">
        <h2 className="text-lg font-semibold">Chat</h2>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} isLoading={isLoading} />
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-50 border-t border-red-200">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {/* Loading Message - Amusing messages while AI works */}
      {loadingMessage && (
        <div className="px-4 py-3 bg-blue-50 border-t border-blue-200">
          <div className="flex items-center space-x-2">
            <div className="flex space-x-1">
              <div className="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
              <div className="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
              <div className="w-2 h-2 bg-blue-600 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
            </div>
            <p className="text-sm text-blue-800 italic">{loadingMessage}</p>
          </div>
        </div>
      )}

      {/* Input */}
      <ChatInput onSend={handleSendMessage} disabled={isLoading} />
    </div>
  );
};
