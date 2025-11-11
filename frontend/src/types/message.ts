import type { SlideDeck } from './slide';

export type MessageRole = 'user' | 'assistant' | 'tool';

export interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

export interface Message {
  role: MessageRole;
  content: string;
  timestamp: string;
  tool_call?: ToolCall;
  tool_call_id?: string;
}

export interface ChatResponse {
  messages: Message[];
  slide_deck: SlideDeck | null;
  metadata: {
    latency_seconds: number;
    tool_calls: number;
  };
}
