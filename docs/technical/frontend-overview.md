# Frontend System Overview

How the React/Vite frontend is structured, how it communicates with backend APIs, and the concepts needed to extend or operate the UI.

---

## Stack & Entry Points

- **Tooling:** Vite + React + TypeScript, Tailwind utility classes, `@dnd-kit` for drag/drop, `@monaco-editor/react` for HTML editing, standard Fetch for API calls.
- **Entrypoint:** `src/main.tsx` injects `<App />` into `#root`. `src/App.tsx` wraps the tree in `ProfileProvider`, `SessionProvider`, `GenerationProvider`, `SelectionProvider` and renders `AppLayout`.
- **Env configuration:** `src/services/api.ts` reads `import.meta.env.VITE_API_URL` (defaults to `http://localhost:8000` in dev, relative URLs in production).

---

## High-Level Layout (`src/components/Layout/AppLayout.tsx`)

```
┌──────────────────────────────────────────────────────────────┐
│ Header: title + session metadata                              │
├──────────────┬──────────────┬─────────────────────────────────┤
│ Chat Panel   │ Selection    │ Slide Panel                     │
│ (32% width)  │ Ribbon       │ (flex-1)                        │
│              │ (fixed 256px)│                                 │
└──────────────┴──────────────┴─────────────────────────────────┘
```

- **ChatPanel** owns chat history and calls backend APIs to generate or edit slides.
- **SelectionRibbon** mirrors the current `SlideDeck` and lets users pick consecutive slides for editing context.
- **SlidePanel** shows parsed slides, raw HTML render, or plain HTML text; exposes per-slide actions (edit, duplicate, delete, reorder).
- **AppLayout** manages shared state:
  - `slideDeck: SlideDeck | null` – parsed slides plus CSS/script metadata
  - `rawHtml: string | null` – exact HTML from the AI for debugging views

---

## Key Concepts

### 1. Session Management

Every user interaction is scoped to a session. The frontend maintains `currentSessionId` in `api.ts`:

```typescript
// src/services/api.ts
let currentSessionId: string | null = null;

api.getOrCreateSession()   // Returns existing or creates new
api.setCurrentSessionId()  // For restoring sessions
api.getCurrentSessionId()  // Access current session
```

All API calls that modify state require `session_id`. Sessions are created lazily on first interaction.

### 2. Slide Deck Contract (`src/types/slide.ts`)

```typescript
interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: { index: number; slide_id: string; html: string }[];
}
```

Slides are HTML snippets embedded in iframes for preview.

### 3. Selection Context (`src/contexts/SelectionContext.tsx`)

- Stores `selectedIndices` and corresponding `Slide[]`
- Enforces contiguous selections via `utils/slideReplacements.ts::isContiguous`
- Shared by Chat + Slide panels so the assistant receives focused context

### 4. Generation Context (`src/contexts/GenerationContext.tsx`)

- Tracks `isGenerating` boolean for navigation locking
- Set by `ChatPanel` during streaming, consumed by `AppLayout`
- Disables navigation buttons, profile selector, and session actions during generation

### 5. Chat Responses (`src/types/message.ts`)

- `ChatResponse` includes messages, `slide_deck`, `raw_html`, and optional `replacement_info`
- `ReplacementInfo` rendered via `ReplacementFeedback` to show slide changes

### 6. View Modes

Parsed tiles, rendered raw HTML (`iframe`), and raw HTML text (`<pre>`). Users can compare parser output vs. model output.

---

## Component Responsibilities

| Path | Responsibility | Backend Touchpoints |
|------|----------------|---------------------|
| `src/components/ChatPanel/ChatPanel.tsx` | Sends prompts via SSE, displays real-time events, loads persisted messages | `api.streamChat`, `api.getSession` |
| `src/components/ChatPanel/ChatInput.tsx` | Textarea with selection badge when context exists | None (props only) |
| `src/components/ChatPanel/MessageList.tsx` & `Message.tsx` | Renders conversation, collapses HTML/tool outputs | None |
| `src/components/SlidePanel/SlidePanel.tsx` | Hosts drag/drop, tabs, per-slide CRUD | `api.getSlides`, `api.reorderSlides`, `api.updateSlide`, `api.duplicateSlide`, `api.deleteSlide` |
| `src/components/SlidePanel/SlideTile.tsx` | Slide preview, selection button, editor modal trigger | Prop callbacks to `SlidePanel` |
| `src/components/SlidePanel/HTMLEditorModal.tsx` | Monaco editor with validation (requires `<div class="slide">`) | Calls `api.updateSlide` then `api.getSlides` |
| `src/components/SlidePanel/SelectionRibbon.tsx` + `SlideSelection.tsx` | Thumbnail strip for contiguous multi-select | None (updates `SelectionContext`) |
| `src/hooks/useKeyboardShortcuts.ts` | `Esc` clears selection globally | None |
| `src/utils/loadingMessages.ts` | Rotating messages during LLM calls | None |

---

## State & Data Flow

### Initialization

1. `AppLayout` renders with `slideDeck = null`
2. `SelectionProvider` ensures any component can call `useSelection()`
3. Session created lazily via `api.getOrCreateSession()` on first chat

### Generating / Editing Slides

1. User enters prompt in `ChatInput`
2. `handleSendMessage` packages text and optional `slideContext`:
   ```typescript
   slideContext = {
     indices: selectedIndices,
     slide_htmls: selectedSlides.map(s => s.html),
   };
   ```
3. `api.sendMessage` POSTs to `/api/chat`:
   ```json
   {
     "session_id": "abc123",
     "message": "...",
     "slide_context": {
       "indices": [0, 1],
       "slide_htmls": ["<div class=\"slide\">...</div>", "..."]
     }
   }
   ```
4. Response updates `messages`, `slideDeck`, and `rawHtml`
5. `SelectionContext` cleared after fresh slides arrive

### Selecting Slides

- `SelectionRibbon` recomputes on deck changes
- Non-contiguous selections show warning and are ignored
- `SlideTile` action button marks single slides
- `SelectionBadge` in `ChatInput` shows current range with clear option

### Slide Operations

| Operation | API Call | Notes |
|-----------|----------|-------|
| **Reorder** | `api.reorderSlides(newOrder, sessionId)` | Optimistic UI with rollback on failure |
| **Duplicate** | `api.duplicateSlide(index, sessionId)` | Returns full updated deck |
| **Delete** | `api.deleteSlide(index, sessionId)` | Returns full updated deck |
| **Edit HTML** | `api.updateSlide(index, html, sessionId)` | Validates `.slide` wrapper |

---

## Backend Interface (`src/services/api.ts`)

### Session Endpoints

| Method | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `createSession` | POST | `/api/sessions` | `{ title? }` | `Session` |
| `listSessions` | GET | `/api/sessions` | query: `limit` | `{ sessions, count }` |
| `getSession` | GET | `/api/sessions/{id}` | – | `Session` |
| `renameSession` | PATCH | `/api/sessions/{id}` | query: `title` | `Session` |
| `deleteSession` | DELETE | `/api/sessions/{id}` | – | – |

### Chat & Slide Endpoints

| Method | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `sendMessage` | POST | `/api/chat` | `{ session_id, message, slide_context? }` | `ChatResponse` |
| `streamChat` | POST | `/api/chat/stream` | `{ session_id, message, slide_context? }` | SSE stream |
| `healthCheck` | GET | `/api/health` | – | `{ status }` |
| `getSlides` | GET | `/api/sessions/{id}/slides` | – | `{ session_id, slide_deck }` |
| `reorderSlides` | PUT | `/api/slides/reorder` | `{ session_id, new_order }` | `SlideDeck` |
| `updateSlide` | PATCH | `/api/slides/{index}` | `{ session_id, html }` | `Slide` |
| `duplicateSlide` | POST | `/api/slides/{index}/duplicate` | `{ session_id }` | `SlideDeck` |
| `deleteSlide` | DELETE | `/api/slides/{index}` | query: `session_id` | `SlideDeck` |

### Error Handling

Errors bubble up as `ApiError` (status + message). Common statuses:
- **409 Conflict** – session is processing another request (retry after delay)
- **404 Not Found** – session or resource doesn't exist
- **400 Bad Request** – validation failure (e.g., non-contiguous indices)

---

## User Flow Reference

1. **Start session** – Load app, session created on first interaction
2. **Generate baseline deck** – Enter prompt, chat panel shows loading, slides appear
3. **Refine slides** – Select contiguous slides via ribbon, provide instructions
4. **Manual adjustments** – Edit HTML via modal, duplicate/delete/reorder
5. **QA raw output** – Compare raw HTML render vs parsed slides

---

## Notes for Contributors & AI Agents

- **Single source of truth:** Backend responses are canonical. Refetch after mutations.
- **Selection integrity:** Always preserve contiguity when setting selections programmatically.
- **Script safety:** `SlideTile` wraps scripts in try/catch for graceful chart failures.
- **Validation:** `HTMLEditorModal` requires `<div class="slide">` wrapper.
- **Session scope:** All operations require valid session ID. Handle 409 with retry/wait UX.
- **Loading UX:** `getRotatingLoadingMessage` keeps UI responsive during long LLM calls.

---

## Extending / Debugging Checklist

1. **New backend call?** Add to `api.ts`, type response in `src/types`, maintain `ApiError` semantics.
2. **Adding shared state?** Use contexts/hooks like `SelectionContext` to avoid prop drilling.
3. **Instrumenting events?** `ChatPanel` is the choke point for AI interactions.
4. **AI agent automation:** Favor SelectionRibbon for multi-select, obey view toggles.
5. **Docs sync:** Update this file and related docs when introducing new paradigms.

---

## Cross-References

- [Backend Overview](backend-overview.md) – FastAPI routes and agent lifecycle
- [Real-Time Streaming](real-time-streaming.md) – SSE events and conversation persistence
- [Multi-User Concurrency](multi-user-concurrency.md) – session locking and async handling
- [Slide Parser & Script Management](slide-parser-and-script-management.md) – HTML parsing and Chart.js reconciliation
