/**
 * Seen-state for AI-feedback findings.
 *
 * Stored client-side in localStorage, never sent to a server:
 *  - per-user by construction (per browser profile), so one user reading a
 *    finding cannot clear another user's highlight on a shared deck;
 *  - survives reload, so reopening a deck does not re-highlight read feedback.
 * Accepted trade-off: does not follow the user to another browser or device.
 */
export const SEEN_STORAGE_KEY = 'tellr-viewer-seen-findings';

// Guard against unbounded growth (spec §5.1.1).
const MAX_DECKS = 50;

type SeenStore = Record<string, string[]>;   // deckKey -> finding ids

function read(): SeenStore {
  try {
    const raw = localStorage.getItem(SEEN_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SeenStore) : {};
  } catch {
    return {};
  }
}

function write(store: SeenStore): void {
  try {
    localStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Quota or disabled storage: seen-state is advisory, so degrade silently.
  }
}

export function loadSeen(deckKey: string): Set<string> {
  return new Set(read()[deckKey] ?? []);
}

export function markSeen(deckKey: string, findingIds: string[]): void {
  if (findingIds.length === 0) return;
  const store = read();
  const merged = new Set([...(store[deckKey] ?? []), ...findingIds]);
  store[deckKey] = Array.from(merged);

  // Trim oldest insertion-ordered deck keys if we exceed the cap (ES2015+ guarantees Object.keys order = insertion order for non-integer string keys, which deckKey always is).
  const keys = Object.keys(store);
  if (keys.length > MAX_DECKS) {
    for (const stale of keys.slice(0, keys.length - MAX_DECKS)) {
      delete store[stale];
    }
  }
  write(store);
}
