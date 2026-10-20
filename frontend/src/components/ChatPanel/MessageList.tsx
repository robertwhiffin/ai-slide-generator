import React, { useEffect, useRef } from 'react';
import { Trash2 } from 'lucide-react';
import type { Message as MessageType } from '../../types/message';
import { Message } from './Message';
import { ChatWelcome } from './ChatWelcome';
import { Button } from '@/ui/button';
import { DELETE_MESSAGE_TOOLTIP } from './deleteMessageCopy';

/** #317: the per-message delete action. Offered on the user's own persisted messages only. */
export interface MessageDeleteAction {
  disabled: boolean;
  onDelete: (messageId: number) => void;
}

interface MessageListProps {
  messages: MessageType[];
  isLoading: boolean;
  /** Absent: no message offers delete (a viewer, an unsaved session, a save-point preview). */
  deleteAction?: MessageDeleteAction;
}

export const MessageList: React.FC<MessageListProps> = ({ messages, isLoading, deleteAction }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="p-4 space-y-4">
      {messages.length === 0 && !isLoading && <ChatWelcome />}

      {messages.map((message, index) => (
        // A named group: Message's own `group-hover` chevrons must not react to this row's hover.
        <div key={index} className="group/row relative" data-testid="chat-message-row">
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
