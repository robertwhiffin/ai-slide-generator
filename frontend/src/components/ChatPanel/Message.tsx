import React, { useState } from 'react';
import type { Message as MessageType } from '../../types/message';

interface MessageProps {
  message: MessageType;
}

export const Message: React.FC<MessageProps> = ({ message }) => {
  const [isExpanded, setIsExpanded] = useState(false);

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

  const renderCollapsibleContent = (
    label: string,
    preview: string,
    content: React.ReactNode,
  ) => (
    <div className={`max-w-3xl rounded-lg p-3 ${getMessageStyle()}`}>
      <button
        onClick={() => setIsExpanded(prev => !prev)}
        className="flex items-center space-x-2 text-sm font-medium text-gray-600 hover:text-gray-800"
        type="button"
      >
        <span>{isExpanded ? '▼' : '▶'}</span>
        <span>{label}</span>
        <span className="text-xs text-gray-500">{preview}</span>
      </button>

      {isExpanded && (
        <div className="mt-2 text-sm text-gray-700 font-mono bg-gray-50 border border-gray-200 rounded p-3 overflow-auto max-h-96">
          {content}
        </div>
      )}
    </div>
  );

  if (message.role === 'tool') {
    return renderCollapsibleContent(
      getMessageLabel(),
      'Tool output',
      <pre className="whitespace-pre-wrap">{message.content}</pre>,
    );
  }

  const trimmedContent = message.content.trimStart();
  const isHtmlContent =
    message.role === 'assistant' &&
    (trimmedContent.includes('<!DOCTYPE html') ||
      trimmedContent.includes('<div class="slide"') ||
      trimmedContent.includes("<div class='slide'"));

  if (isHtmlContent) {
    return renderCollapsibleContent(
      `${getMessageLabel()} (HTML)`,
      'Generated slide HTML',
      <pre className="whitespace-pre-wrap text-xs">
        {message.content}
      </pre>,
    );
  }

  // Tool call messages - show as collapsible accordion
  if (message.tool_call) {
    const toolArgs = message.tool_call.arguments;
    const argsPreview = toolArgs?.query 
      ? `"${toolArgs.query.slice(0, 50)}${toolArgs.query.length > 50 ? '...' : ''}"`
      : '';
    
    return renderCollapsibleContent(
      `Tool call: ${message.tool_call.name}`,
      argsPreview,
      <pre className="whitespace-pre-wrap text-xs">
        {JSON.stringify(message.tool_call.arguments, null, 2)}
      </pre>,
    );
  }

  return (
    <div className={`max-w-3xl rounded-lg p-4 ${getMessageStyle()}`}>
      <div className="text-xs font-semibold text-gray-500 mb-1">
        {getMessageLabel()}
      </div>
      <div className="text-sm text-gray-800 whitespace-pre-wrap">
        {message.content}
      </div>
    </div>
  );
};
