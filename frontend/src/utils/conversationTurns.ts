/**
 * Conversation turns in the chat panel (#317). A turn is a user message and every message after
 * it up to (not including) the next user message: the same span the backend deletes for
 * DELETE /api/sessions/{id}/messages/{messageId} (src/domain/conversation_turns.py).
 */
import type { Message } from '../types/message';
import type { SessionMessage } from '../services/api';

/** `messages` without the turn whose user message has id `userMessageId`; unchanged if there is none. */
export function withoutTurn(messages: Message[], userMessageId: number): Message[] {
  const start = messages.findIndex(m => m.role === 'user' && m.id === userMessageId);
  if (start === -1) return messages;
  let end = start + 1;
  while (end < messages.length && messages[end].role !== 'user') end += 1;
  return [...messages.slice(0, start), ...messages.slice(end)];
}

/**
 * Give the panel's id-less user messages the ids of the persisted rows they are.
 *
 * A message sent in this panel is shown before the server stores it, so it has no id, and the
 * delete action needs one. After a turn the panel lists the persisted rows and pairs them from
 * the newest: each id-less user message takes the newest unpaired persisted user row with exactly
 * the same content that is older than every row paired or carried AFTER it and newer than every
 * row carried BEFORE it. Pairing from the newest keeps a send that failed before it was stored
 * (often retried with the same text) from taking the retry's id.
 *
 * Only adds ids: never changes content, order or any other message. A message with no identical
 * row keeps no id and gets one on the next full load. Returns `panel` itself when nothing changed.
 */
export function withPersistedUserIds(panel: Message[], persisted: SessionMessage[]): Message[] {
  const rows = persisted.filter(r => r.role === 'user' && typeof r.id === 'number');
  const rowIndex = (id: number) => rows.findIndex(r => r.id === id);
  const taken = new Set(panel.flatMap(m => (typeof m.id === 'number' ? [m.id] : [])));
  // floor[p]: index (in rows) of the newest row already carried by a message at or before p.
  // A message may only pair with a row NEWER than that, so it never jumps behind an identified one.
  const floor: number[] = [];
  let seen = -1;
  panel.forEach((m, i) => {
    if (m.role === 'user' && typeof m.id === 'number') seen = Math.max(seen, rowIndex(m.id));
    floor[i] = seen;
  });
  const next = [...panel];
  let limit = rows.length;  // only rows[floor[p]+1 .. limit) may still be paired
  let changed = false;
  for (let p = next.length - 1; p >= 0; p -= 1) {
    const message = next[p];
    if (message.role !== 'user') continue;
    if (typeof message.id === 'number') {
      const at = rowIndex(message.id);
      if (at !== -1 && at < limit) limit = at;
      continue;
    }
    for (let r = limit - 1; r > floor[p]; r -= 1) {
      const row = rows[r];
      if (!taken.has(row.id) && row.content === message.content) {
        next[p] = { ...message, id: row.id };
        taken.add(row.id);
        limit = r;
        changed = true;
        break;
      }
    }
  }
  return changed ? next : panel;
}
