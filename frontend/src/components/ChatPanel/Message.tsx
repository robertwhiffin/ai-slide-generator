import React, { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import type { Message as MessageType } from '../../types/message';
import { splitDeckAdvisory, splitFindingRequest } from '../../utils/findingText';

// Human labels for the keys a failure notice's details carry; unknown keys render as-is.
const DETAIL_LABELS: Record<string, string> = {
  stage: 'Stage',
  error: 'Error',
  request_id: 'Request ID',
};

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
  // Slide HTML arrives in two shapes: a full document on initial creation
  // (starts with <!DOCTYPE html>) and bare slide divs on revisions. Real slides
  // use compound classes like `class="slide content"`, so match the `slide`
  // class token anywhere in a div's class list — not just an exact
  // `class="slide"` substring — to mirror the backend's `class_="slide"` parsing.
  const SLIDE_DIV_PATTERN =
    /<div\b[^>]*\bclass\s*=\s*["'](?:[^"']*\s)?slide(?:\s[^"']*)?["']/i;
  const isHtmlContent =
    message.role === 'assistant' &&
    (trimmedContent.includes('<!DOCTYPE html') ||
      SLIDE_DIV_PATTERN.test(trimmedContent));

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
  // #321: a failure notice's technical half (metadata.details), assistant messages only.
  const detailEntries =
    message.role === 'assistant' && message.details
      ? Object.entries(message.details)
      : [];
  // #316: collapse the reviewer's technical section of exactly the two shapes this
  // PR writes (Apply/Discuss requests from the user; the deck-review advisory from
  // the assistant).  Strict match, role-bound; any other content renders verbatim.
  // Render-only: what was sent and stored is unchanged.
  const split = isUser
    ? splitFindingRequest(message.content)
    : message.role === 'assistant'
      ? splitDeckAdvisory(message.content)
      : null;
  // Full-opacity foreground on the primary bubble: white on primary is 5.2:1;
  // /80 would be 3.9:1, below AA at this size.
  const detailsTone = isUser ? 'text-primary-foreground' : 'text-muted-foreground';

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
          {split ? split.lead : message.content}
        </div>
        {split && (
          <details className={`mt-2 text-xs ${detailsTone}`} data-testid="message-reviewer-details">
            <summary className="cursor-pointer select-none underline-offset-2 hover:underline">
              Reviewer's details
            </summary>
            <div className="mt-1 whitespace-pre-wrap break-words">{split.details}</div>
          </details>
        )}
        {detailEntries.length > 0 && (
          <details className="mt-2 text-xs text-muted-foreground" data-testid="message-details">
            <summary className="cursor-pointer select-none">Details</summary>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 font-mono">
              {detailEntries.map(([key, value]) => (
                <React.Fragment key={key}>
                  <dt>{DETAIL_LABELS[key] ?? key}</dt>
                  <dd className="break-all">{value}</dd>
                </React.Fragment>
              ))}
            </dl>
          </details>
        )}
      </div>
    </div>
  );
};
