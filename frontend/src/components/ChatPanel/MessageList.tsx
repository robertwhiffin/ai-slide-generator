import React, { useEffect, useRef } from 'react';
import type { Message as MessageType } from '../../types/message';
import { Message } from './Message';
import { ChatWelcome } from './ChatWelcome';
import { DEFAULT_TURN_LABEL } from '../../utils/turnProgress';

interface MessageListProps {
  messages: MessageType[];
  isLoading: boolean;
  /** #319: the stage label; defaults to the generic text. */
  progressLabel?: string;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading,
  progressLabel = DEFAULT_TURN_LABEL,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="p-4 space-y-4">
      {messages.length === 0 && !isLoading && <ChatWelcome />}

      {messages.map((message, index) => (
        <Message key={index} message={message} />
      ))}
      
      {isLoading && (
        <div
          className="flex items-center space-x-2 text-gray-500"
          data-testid="chat-turn-progress"
          aria-live="polite"
          aria-atomic="true"
        >
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-500"></div>
          <span className="text-sm">{progressLabel}</span>
        </div>
      )}
      
      <div ref={bottomRef} />
    </div>
  );
};
