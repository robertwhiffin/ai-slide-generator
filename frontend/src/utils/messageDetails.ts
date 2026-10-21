import type { MessageDetails } from '../types/message';

/**
 * Narrow whatever the backend sent as `metadata.details` to the string-to-string map the chat's
 * Details disclosure renders. Returns a fresh object holding only the non-empty string values, or
 * `undefined` (render no disclosure) for non-objects, arrays, and when nothing is left.
 */
export function readMessageDetails(value: unknown): MessageDetails | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const entries = Object.entries(value as Record<string, unknown>).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1] !== '',
  );
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}
