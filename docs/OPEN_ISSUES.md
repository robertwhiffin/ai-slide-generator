# Open issues (to revisit later)

Issues that are tabled but should be revisited.

---

## ~~Sidebar: deck name and slide number not updating~~

**Status:** Resolved — removed redundant `autoSaveSession` in fix/remove-redundant-autosave.

**Root cause:** PR #125 added a frontend `autoSaveSession` that called `renameSession(deck.title, count)` after generation. This overwrote the backend-generated session title (from `run_title_gen` → `session_manager.rename_session`) with the deck's content title, which could be empty or different. The backend already persists both title (via LLM naming on first message) and slide_count (via `save_slide_deck`), so the frontend call was redundant and destructive.
