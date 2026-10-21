import type { SlideDeck, ReplacementInfo } from './slide';

export type MessageRole = 'user' | 'assistant' | 'tool';

export interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

export interface Message {
  /** Persisted SessionMessage.id. Absent on a message this panel has shown but not yet matched
   *  to its row (a just-sent or streamed one); only messages with an id can be deleted (#317). */
  id?: number;
  role: MessageRole;
  content: string;
  timestamp: string;
  tool_call?: ToolCall;
  tool_call_id?: string;
}

export interface ChatMetadata {
  latency_seconds: number;
  tool_calls: number;
  message_count?: number;
  mode?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface ChatResponse {
  messages: Message[];
  slide_deck: SlideDeck | null;
  raw_html: string | null;
  metadata: ChatMetadata;
  replacement_info?: ReplacementInfo;
}
