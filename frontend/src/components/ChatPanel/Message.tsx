import React, { useState } from 'react';
import type { Message as MessageType } from '../../types/message';

interface MessageProps {
  message: MessageType;
}

export const Message: React.FC<MessageProps> = ({ message }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // Style based on role
  const getMessageStyle = () => {
    switch (message.role) {
      case 'user':
        return 'bg-blue-100 ml-auto';
      case 'assistant':
        return 'bg-white';
      case 'tool':
        return 'bg-gray-100';
      default:
        return 'bg-gray-50';
    }
  };

  const getMessageLabel = () => {
    switch (message.role) {
      case 'user':
        return 'You';
      case 'assistant':
        return 'AI Assistant';
      case 'tool':
        return 'Tool Result';
      default:
        return message.role;
    }
  };

  // For tool messages, make them collapsible
  if (message.role === 'tool') {
    return (
      <div className={`max-w-3xl rounded-lg p-3 ${getMessageStyle()}`}>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center space-x-2 text-sm font-medium text-gray-600 hover:text-gray-800"
        >
          <span>{isExpanded ? '▼' : '▶'}</span>
          <span>{getMessageLabel()}</span>
        </button>
        
        {isExpanded && (
          <div className="mt-2 text-sm text-gray-600 font-mono whitespace-pre-wrap">
            {message.content}
          </div>
        )}
      </div>
    );
  }

  // For assistant messages that are HTML (very long), truncate display
  const isHtmlContent = message.content.includes('<!DOCTYPE html>');
  const displayContent = isHtmlContent 
    ? 'Generated slide deck HTML (view in Slides panel →)'
    : message.content;

  return (
    <div className={`max-w-3xl rounded-lg p-4 ${getMessageStyle()}`}>
      <div className="text-xs font-semibold text-gray-500 mb-1">
        {getMessageLabel()}
      </div>
      <div className="text-sm text-gray-800 whitespace-pre-wrap">
        {displayContent}
      </div>
      {message.tool_call && (
        <div className="mt-2 text-xs text-gray-500">
          Tool: {message.tool_call.name}
        </div>
      )}
    </div>
  );
};
