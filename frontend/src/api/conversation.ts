/**
 * Conversation API: calls that change a session's CONVERSATION, never its deck.
 * Clear chat (#323) lives here; #317 (delete a message) adds its call beside it.
 * Errors are the app's existing ApiError (services/api.ts), so #317 reuses one type.
 */
import { ApiError, type SessionMessage } from '../services/api';

const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

export interface ClearChatResult {
  status: 'cleared';
  session_id: string;
  deleted_messages: number;
  preserved_message_id: number | null;
}

export interface DeleteMessageResult {
  status: 'deleted';
  session_id: string;
  message_id: number;
  deleted_messages: number;
  hidden_message_id: number | null;
}

export interface SessionMessagesResult {
  session_id: string;
  messages: SessionMessage[];
  count: number;
}

async function errorFrom(response: Response, fallback: string): Promise<ApiError> {
  let message = fallback;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === 'string' && detail) message = detail;
    else if (detail && typeof detail.message === 'string') message = detail.message;
  } catch {
    // Non-JSON body: keep the fallback.
  }
  return new ApiError(response.status, message);
}

export const conversationApi = {
  /** DELETE /api/sessions/{id}/context: clears THIS session's conversation only. */
  async clearChat(sessionId: string): Promise<ClearChatResult> {
    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/context`,
      { method: 'DELETE' },
    );
    if (!response.ok) throw await errorFrom(response, 'Failed to clear the chat');
    return response.json();
  },

  /** DELETE /api/sessions/{id}/messages/{messageId}: deletes that message and its replies, in THIS session only. */
  async deleteMessage(sessionId: string, messageId: number): Promise<DeleteMessageResult> {
    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(String(messageId))}`,
      { method: 'DELETE' },
    );
    if (!response.ok) throw await errorFrom(response, 'Failed to delete the message');
    return response.json();
  },

  /**
   * GET /api/sessions/{id}/messages: the persisted conversation, with ids (session creator only).
   * With `limit`, only the newest `limit` rows (the backend keeps `messages[-limit:]`).
   */
  async listMessages(sessionId: string, limit?: number): Promise<SessionMessagesResult> {
    const query = limit != null ? `?limit=${encodeURIComponent(String(limit))}` : '';
    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/messages${query}`,
    );
    if (!response.ok) throw await errorFrom(response, 'Failed to load the conversation');
    return response.json();
  },
};
