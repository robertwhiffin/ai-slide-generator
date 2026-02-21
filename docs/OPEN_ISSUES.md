# Open issues (to revisit later)

Issues that are tabled but should be revisited.

---

## Sidebar: deck name and slide number not updating

**Status:** Tabled for later.

**Observed:** Last-saved time per deck is updated correctly in the sidebar. Deck name (session title) and slide count are still not showing correctly in the sidebar/list after generation (or after other updates).

**Context:** We implemented:
- After generation: save deck name + slide count via `autoSaveSession(deck)` → `renameSession(deck.title, deck.slide_count)` or `updateSession(sessionId, { slide_count })`.
- Backend PATCH session accepts `title` and `slide_count`; `update_session` persists both to `user_sessions.title` and `session_slide_decks.slide_count`.
- Sidebar reads only from `listSessions()` (no live overrides).

**Possible causes to investigate later:** Refetch timing (list loaded before DB commit), backend list_sessions not returning updated values, or frontend not calling save in the right place. See conversation summary for debugging options (verify backend write, refetch delay, or temporary live override for current session only).

**Revisit when:** Prioritizing sidebar/list correctness for deck name and slide count.
