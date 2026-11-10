import type { SlideDeck, ReplacementInfo } from './slide';

export type MessageRole = 'user' | 'assistant' | 'tool';

export interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

/** Technical detail behind a plain-language notice (stage, error, request id), keyed by name. */
export type MessageDetails = Record<string, string>;

export interface Message {
  /** Persisted SessionMessage.id. Absent on a message this panel has shown but not yet matched
   *  to its row (a just-sent or streamed one); only messages with an id can be deleted (#317). */
  id?: number;
  role: MessageRole;
  content: string;
  timestamp: string;
  tool_call?: ToolCall;
  tool_call_id?: string;
  /** Technical detail behind a plain-language notice; never the headline. */
  details?: MessageDetails;
  /** Which agent wrote this message; 'data_analyst' draws the collapsed analyst card. */
  agent?: string;
  /** The link a Gateway sign-in notice says (the server marks the row with metadata.sign_in_url).
   *  The only URL chat ever renders as a link, and only when it is https. */
  sign_in_url?: string;
  /** Images generated with this reply (shown as an options card under it). */
  generated_images?: GeneratedImageRef[];
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

export type GeneratedImageKind = 'illustration' | 'background' | 'icon' | 'vector_icon';

/** One image the architect generated in a turn (server metadata `generated_images`). */
export interface GeneratedImageRef {
  token: string;
  kind: GeneratedImageKind;
  option: number;
  prompt?: string;
  for_slide?: number | null;
  /** 1-based slides the image is placed on; empty while it is only an option. */
  slides: number[];
}
