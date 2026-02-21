# Deck generator page reload – root cause and fix plan

## Problem

On the deck generator page (main view at `/sessions/:sessionId/edit`), when content is loading:

- The **title in the header** and the **panels** (especially the AI assistant chat) appear to “reload” (remount or re-render multiple times).

## Root causes

### 1. urlSessionId effect re-runs when sessionId changes and overwrites (primary bug)

The "restore session from URL" effect depends on `[urlSessionId, sessionId, slideDeck, ...]`. When the user clicks a deck in the sidebar: (1) `handleSessionRestore(B)` runs and calls `switchSession(B)`; (2) context updates so `sessionId` becomes B (URL is still `/sessions/A/edit`); (3) the effect runs again because `sessionId` changed; (4) `urlSessionId` is still A; (5) the effect calls `switchSession(A)` and overwrites with A's deck → visible reload. **Fix:** ref `restoringSessionIdRef` set in `handleSessionRestore`, cleared in `finally`; effect skips when `restoringSessionIdRef.current === sessionId`.

### 2. ChatPanel was forced to remount via `chatKey` (fixed earlier)

- `AppLayout` rendered `<ChatPanel key={chatKey} />`. Whenever `setChatKey` is called, `chatKey` changes, so React unmounts the old `ChatPanel` and mounts a new one → visible “reload” of the chat panel.
- `setChatKey` is used in four places:
  - **handleSessionRestore (start)** – to cancel in-flight chat polling when switching decks.
  - **urlSessionId effect (after restore)** – after loading session from URL; no need to remount.
  - **handleNewSession** – to “reset” chat for a new deck.
  - **handleProfileChange** – to “reset” chat when changing profile.

So whenever we load a deck (from sidebar or from URL) or start a new session or change profile, the chat panel remounts at least once, which is what the user sees as “panels reloading”.

### 3. Unnecessary remount when loading from URL (fixed earlier)

- The **urlSessionId** effect (restore session when landing on `/sessions/:id/edit`) calls `setChatKey((k) => k + 1)` after `switchSession` and `setSlideDeck`/`setRawHtml`. There is no in-flight poll to cancel when we’ve just loaded the page, so this remount is unnecessary.

### 4. Header title and main content re-render (mitigated by above)

- Restore flow does several state updates in sequence: context update from `switchSession` (sessionId, sessionTitle), then `setSlideDeck`, `setRawHtml`, `setLastSavedTime`, `setViewMode`, and (currently) `setChatKey`. Each batch of updates causes a re-render.
- Header title is `slideDeck?.title || sessionTitle || 'Untitled session'`. It updates when `sessionTitle` (from context) updates and again when `slideDeck` is set, so the title can change more than once during load and look like a “reload” even though the header component isn’t remounting.

The main visible issue is the **ChatPanel remount**; reducing re-renders helps the title feel stable.

## Fix plan

### 1. Cancel in-flight polling when `sessionId` changes (ChatPanel)

- In `ChatPanel`, add a `useEffect` that depends on `sessionId` and whose **cleanup** calls `cancelStreamRef.current?.()` (and clears `intervalRef` if needed). That way, when the user switches deck or creates a new session, the previous session’s polling is cancelled without remounting the panel.
- Rely on the existing `useEffect([sessionId])` to load messages for the new session.

### 2. Stop forcing ChatPanel remount from AppLayout

- **handleSessionRestore**: Remove the initial `setChatKey((k) => k + 1)`. Polling will be cancelled by ChatPanel’s sessionId cleanup.
- **urlSessionId effect**: Remove `setChatKey((k) => k + 1)` after restore. No need to remount when loading from URL.
- **handleNewSession**: Remove `setChatKey((k) => k + 1)`. New sessionId will trigger ChatPanel to load (empty) messages and cleanup will cancel any previous poll.
- **handleProfileChange**: Remove `setChatKey((prev) => prev + 1)`. Profile change creates a new session (new sessionId), so again sessionId-based cleanup and load are enough.

### 3. Stable ChatPanel identity

- Use a **stable key** for `ChatPanel` (e.g. `key="chat-panel"`) so it never remounts due to key change. Then remove the `chatKey` state from `AppLayout` and all `setChatKey` calls.

Result:

- Chat panel no longer remounts when loading a deck (from sidebar or URL), when starting a new session, or when changing profile. It only re-renders and runs effects when `sessionId` (and other props) change.
- Fewer state updates and no chat remount mean the header and the rest of the main content re-render less and the title settles faster, reducing the “reloading” feel.

## Files changed

1. **frontend/src/components/ChatPanel/ChatPanel.tsx**  
   - Added `useEffect` with dependency `[sessionId]` and cleanup that cancels stream and clears loading interval.

2. **frontend/src/components/Layout/AppLayout.tsx**  
   - Removed `chatKey` state and all `setChatKey` usages; render ChatPanel with stable `key="chat-panel"`.
   - Added `restoringSessionIdRef` and skip the urlSessionId effect when `restoringSessionIdRef.current === sessionId`; set ref at start of `handleSessionRestore`, clear in `finally`.
