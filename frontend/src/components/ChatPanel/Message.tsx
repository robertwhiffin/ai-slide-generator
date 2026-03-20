import React, { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import type { Message as MessageType } from '../../types/message';

interface MessageProps {
  message: MessageType;
}

export const Message: React.FC<MessageProps> = ({ message }) => {
  const [isExpanded, setIsExpanded] = useState(false);

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
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-xl bg-muted/50 px-3.5 py-2.5">
        <button
          onClick={() => setIsExpanded(prev => !prev)}
          className="group flex w-full items-center justify-between gap-2 text-left text-sm font-medium text-foreground hover:text-foreground/70 transition-colors"
          type="button"
        >
          <span className="flex-1">
            <span className="block">{label}</span>
            {preview && (
              <span className="block text-xs font-normal text-muted-foreground mt-0.5">
                {preview}
              </span>
            )}
          </span>
          {isExpanded ? (
            <ChevronDown className="size-4 shrink-0 text-muted-foreground opacity-40 group-hover:opacity-100 transition-opacity" />
          ) : (
            <ChevronRight className="size-4 shrink-0 text-muted-foreground opacity-40 group-hover:opacity-100 transition-opacity" />
          )}
        </button>

        {isExpanded && (
          <div className="mt-2 text-[13px] leading-relaxed text-muted-foreground font-mono bg-background border border-border rounded p-3 overflow-auto max-h-96">
            {content}
          </div>
        )}
      </div>
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
    // Extract query - handle both direct string and nested object
    let queryText = '';
    if (typeof toolArgs?.query === 'string') {
      queryText = toolArgs.query;
    } else if (typeof toolArgs === 'object') {
      // Try to find a query-like field
      queryText = toolArgs.query || toolArgs.input || JSON.stringify(toolArgs);
    }

    const argsPreview = queryText
      ? `"${queryText.slice(0, 60)}${queryText.length > 60 ? '...' : ''}"`
      : '';

    return renderCollapsibleContent(
      `Tool call: ${message.tool_call.name}`,
      argsPreview,
      <div className="text-xs">
        {queryText ? (
          <div>
            <span className="text-muted-foreground">Query: </span>
            <span className="text-foreground">{queryText}</span>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap">
            {JSON.stringify(message.tool_call.arguments, null, 2)}
          </pre>
        )}
      </div>,
    );
  }

  // Regular user/assistant messages with v0 styling
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
          message.role === 'assistant'
            ? 'bg-muted/50 text-foreground'
            : 'bg-primary text-primary-foreground'
        }`}
      >
        <div className="whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    </div>
  );
};
