import React, { useEffect, useRef } from 'react';
import { Trash2 } from 'lucide-react';
import type { Message as MessageType } from '../../types/message';
import { Message } from './Message';
import { ToolActivityBar } from './ToolActivityBar';
import { ChatWelcome } from './ChatWelcome';
import { Button } from '@/ui/button';
import { DEFAULT_TURN_LABEL } from '../../utils/turnProgress';
import { DELETE_MESSAGE_TOOLTIP } from './deleteMessageCopy';

/** #317: the per-message delete action. Offered on the user's own persisted messages only. */
export interface MessageDeleteAction {
  disabled: boolean;
  onDelete: (messageId: number) => void;
}

interface MessageListProps {
  messages: MessageType[];
  isLoading: boolean;
  /** #319: the stage label; defaults to the generic text. */
  progressLabel?: string;
  /** Absent: no message offers delete (a viewer, an unsaved session, a save-point preview). */
  deleteAction?: MessageDeleteAction;
}

const isToolMessage = (m: MessageType): boolean => Boolean(m.tool_call) || m.role === 'tool';

type Row =
  | { kind: 'tool'; start: number; messages: MessageType[] }
  | { kind: 'message'; start: number; message: MessageType };

/** Group each consecutive run of tool messages into one row; other messages stay single rows. */
function groupRows(messages: MessageType[]): Row[] {
  const rows: Row[] = [];
  messages.forEach((message, index) => {
    const prev = rows[rows.length - 1];
    if (isToolMessage(message)) {
      if (prev?.kind === 'tool') prev.messages.push(message);
      else rows.push({ kind: 'tool', start: index, messages: [message] });
    } else {
      rows.push({ kind: 'message', start: index, message });
    }
  });
  return rows;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading,
  progressLabel = DEFAULT_TURN_LABEL,
  deleteAction,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="p-4 space-y-4">
      {messages.length === 0 && !isLoading && <ChatWelcome />}

      {groupRows(messages).map((row) => {
        if (row.kind === 'tool') {
          return (
            <div key={row.start} data-testid="chat-message-row">
              <ToolActivityBar messages={row.messages} />
            </div>
          );
        }
        const message = row.message;
        return (
        // A named group: Message's own `group-hover` chevrons must not react to this row's hover.
        <div key={row.start} className="group/row relative" data-testid="chat-message-row">
          <Message message={message} />
          {deleteAction && message.role === 'user' && typeof message.id === 'number' && (
            <Button
              type="button"
              data-testid="delete-message-button"
              size="icon"
              variant="ghost"
              // Shown on hover and focus only. `disabled:opacity-0` replaces Button's base
              // `disabled:opacity-50`, which would otherwise show every disabled button all the time
              // (during every turn); a hovered disabled button is shown greyed.
              className="absolute left-0 top-1/2 size-7 -translate-y-1/2 opacity-0 transition-opacity group-hover/row:opacity-100 focus-visible:opacity-100 disabled:opacity-0 group-hover/row:disabled:opacity-50"
              title={DELETE_MESSAGE_TOOLTIP}
              aria-label={DELETE_MESSAGE_TOOLTIP}
              disabled={deleteAction.disabled}
              onClick={() => deleteAction.onDelete(message.id as number)}
            >
              <Trash2 />
            </Button>
          )}
        </div>
        );
      })}

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
