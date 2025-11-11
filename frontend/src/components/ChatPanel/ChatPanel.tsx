import React, { useState } from 'react';
import type { Message } from '../../types/message';
import type { SlideDeck } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { api } from '../../services/api';

interface ChatPanelProps {
  onSlidesGenerated: (slideDeck: SlideDeck) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ onSlidesGenerated }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSendMessage = async (content: string, maxSlides: number) => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await api.sendMessage(content, maxSlides);
      
      // Add new messages to chat
      setMessages(prev => [...prev, ...response.messages]);
      
      // Pass slide deck to parent
      if (response.slide_deck) {
        onSlidesGenerated(response.slide_deck);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setIsLoading(false);
    }
  };

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

      {/* Input */}
      <ChatInput onSend={handleSendMessage} disabled={isLoading} />
    </div>
  );
};
