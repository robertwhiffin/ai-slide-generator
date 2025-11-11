import React, { useEffect, useRef } from 'react';
import { Message as MessageType } from '../../types/message';
import { Message } from './Message';

interface MessageListProps {
  messages: MessageType[];
  isLoading: boolean;
}

export const MessageList: React.FC<MessageListProps> = ({ messages, isLoading }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="p-4 space-y-4">
      {messages.map((message, index) => (
        <Message key={index} message={message} />
      ))}
      
      {isLoading && (
        <div className="flex items-center space-x-2 text-gray-500">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-500"></div>
          <span className="text-sm">Generating slides...</span>
        </div>
      )}
      
      <div ref={bottomRef} />
    </div>
  );
};

