# Frontend System Overview

This document explains how the React/Vite frontend in `frontend/` is structured, how it talks to the backend APIs, and the concepts you need to understand to extend or operate the UI. Use it as a quick-start for both humans and AI agents.

---

## Stack & Entry Points

- **Tooling:** Vite + React + TypeScript, Tailwind utility classes, `@dnd-kit` for drag/drop, `@monaco-editor/react` for HTML editing, and standard Fetch for API calls.
- **Entrypoint:** `src/main.tsx` injects `<App />` into `#root`. `src/App.tsx` wraps the tree in `SelectionProvider` and renders `AppLayout`.
- **Env configuration:** `src/services/api.ts` reads `import.meta.env.VITE_API_URL` (defaults to `http://localhost:8000`). Every request is rooted at `${API_BASE_URL}/api/...`.

---

## High-Level Layout (`src/components/Layout/AppLayout.tsx`)

```
┌──────────────────────────────────────────────────────────┐
│ Header: title + session metadata                          │
├──────────────┬──────────────┬─────────────────────────────┤
│ Chat Panel   │ Selection    │ Slide Panel                 │
│ (32% width)  │ Ribbon       │ (flex-1)                    │
│              │ (fixed 256px)│                             │
└──────────────┴──────────────┴─────────────────────────────┘
```

- `ChatPanel` owns the chat history and calls backend APIs to generate or edit slides.
- `SelectionRibbon` mirrors the current `SlideDeck` and lets users pick consecutive slides that should be passed as editing context.
- `SlidePanel` shows the parsed slides, the raw HTML render, or plain HTML text and exposes per-slide actions (edit, duplicate, delete, reorder).
- `AppLayout` keeps two pieces of shared state:
  - `slideDeck: SlideDeck | null` – the parsed slides plus CSS/script metadata.
  - `rawHtml: string | null` – the exact HTML payload returned from the AI, used for debugging views.

---

## Key Concepts

1. **Slide Deck contract (`src/types/slide.ts`):**
   ```ts
   interface SlideDeck {
     title: string;
     slide_count: number;
     css: string;
     external_scripts: string[];
     scripts: string;
     slides: { index: number; slide_id: string; html: string }[];
   }
   ```
   The frontend always treats slides as HTML snippets that are embedded inside an iframe for preview.

2. **Selection context (`src/contexts/SelectionContext.tsx`):**
   - Stores `selectedIndices` and the corresponding `Slide[]`.
   - Enforces contiguous selections via `utils/slideReplacements.ts::isContiguous`.
   - Shared by Chat + Slide panels so the assistant receives focused context.

3. **Chat responses (`src/types/message.ts`):**
   - `ChatResponse` includes assistant/user/tool messages, `slide_deck`, `raw_html`, and optional `replacement_info`.
   - `ReplacementInfo` is rendered via `ReplacementFeedback` to show how many slides changed.

4. **View modes:**
   - Parsed tiles, rendered raw HTML (`iframe`), and raw HTML text (`<pre>`). Users can compare what the parser produced vs. what the model emitted.

5. **Phase notes:** Comments in `api.ts` flag future `session_id` support (Phase 4). Leave space for threading once backend ships it.

---

## Component Responsibilities

| Path | Responsibility | Backend Touchpoints |
| --- | --- | --- |
| `src/components/ChatPanel/ChatPanel.tsx` | Sends prompts, streams loading UX, records messages, handles replacement summaries. | `api.sendMessage` |
| `src/components/ChatPanel/ChatInput.tsx` | Textarea with `maxSlides` control, shows selection badge when context exists. | None (props only) |
| `src/components/ChatPanel/MessageList.tsx` & `Message.tsx` | Renders conversation, collapses HTML/tool outputs. | None |
| `src/components/SlidePanel/SlidePanel.tsx` | Hosts drag/drop, tabs, and per-slide CRUD. | `getSlides`, `reorderSlides`, `updateSlide`, `duplicateSlide`, `deleteSlide` |
| `src/components/SlidePanel/SlideTile.tsx` | Visual slide preview, selection button, html editor modal trigger. | Prop callbacks to `SlidePanel` |
| `src/components/SlidePanel/HTMLEditorModal.tsx` | Monaco editor with validations (requires `<div class="slide">`). | Calls `onSave` which awaits `api.updateSlide` and `api.getSlides`. |
| `src/components/SlidePanel/SelectionRibbon.tsx` + `SlideSelection.tsx` | Thumbnail strip for contiguous multi-select, warns on invalid ranges. | None (updates `SelectionContext`) |
| `src/hooks/useKeyboardShortcuts.ts` | Press `Esc` to clear selection globally. | None |
| `src/utils/loadingMessages.ts` | Rotating “fun” strings shown while backend works. | None |

---

## State & Data Flow

1. **Initialization**
   - `AppLayout` renders with `slideDeck = null`. Chat instructs user to request slides.
   - `SelectionProvider` ensures any component can call `useSelection()`.

2. **Generating / editing slides**
   - User enters a prompt in `ChatInput`. `handleSendMessage` packages the text, `maxSlides`, and optional `slideContext`:
     ```ts
     slideContext = {
       indices: selectedIndices,
       slide_htmls: selectedSlides.map(s => s.html),
     };
     ```
   - `api.sendMessage` POSTs to `/api/chat`:
     ```json
     {
       "message": "...",
       "max_slides": 10,
       "slide_context": {
         "indices": [0,1],
         "slide_htmls": ["<div class=\"slide\">...</div>", "..."]
       }
     }
     ```
   - Response updates `messages`, `slideDeck`, and `rawHtml`. `SelectionContext` is cleared once fresh slides arrive to avoid stale references.

3. **Selecting slides**
   - `SelectionRibbon` re-computes `slides` any time the deck changes. Non-contiguous selections show a warning and are ignored.
   - `SlideTile` action button lets you mark a single slide without leaving the panel.
   - `SelectionBadge` in `ChatInput` mirrors the current range and lets users clear it inline.

4. **Slide operations**
   - **Reorder:** Dragging triggers an optimistic `arrayMove`, then `api.reorderSlides(newOrder)` sends an array of indices to `/api/slides/reorder`. On failure the deck is reverted.
   - **Duplicate/Delete:** `api.duplicateSlide(index)` (POST `/api/slides/{index}/duplicate`) and `api.deleteSlide(index)` (DELETE `/api/slides/{index}`) both return the full updated deck.
   - **Edit HTML:** `HTMLEditorModal` validates content, then `api.updateSlide(index, html)` PATCHes `/api/slides/{index}`. After success the client refetches `/api/slides` to hydrate derived fields like `slide_count`.
   - **Raw views:** `rawHtml` is displayed either rendered (`iframe srcDoc`) or as text to debug parsing drift.

---

## Backend Interface Details (`src/services/api.ts`)

| Method | HTTP | Path | Request Body | Returns | Usage |
| --- | --- | --- | --- | --- | --- |
| `sendMessage` | POST | `/api/chat` | `{ message, max_slides, slide_context? }` | `ChatResponse` | Generate or modify slides via LLM |
| `healthCheck` | GET | `/api/health` | – | `{ status: "ok" }` | Optional readiness probes |
| `getSlides` | GET | `/api/slides` | – | `SlideDeck` | Refresh after manual edits |
| `reorderSlides` | PUT | `/api/slides/reorder` | `{ new_order: number[] }` | `SlideDeck` | Persist drag/drop order |
| `updateSlide` | PATCH | `/api/slides/{index}` | `{ html }` | `Slide` | Save single-slide HTML |
| `duplicateSlide` | POST | `/api/slides/{index}/duplicate` | – | `SlideDeck` | Clone slide in place |
| `deleteSlide` | DELETE | `/api/slides/{index}` | – | `SlideDeck` | Remove slide |

Errors bubble up as `ApiError` (status + message). Callers catch and either show an `ErrorDisplay` (chat) or `alert()` (slide panel). Consider standardizing toast UX if more surfaces are added.

---

## User Flow Reference

1. **Start session**
   - Load app, run health check if desired.
2. **Generate baseline deck**
   - Enter prompt (e.g., “Create a slide deck about quarterly revenue”).
   - Chat panel shows rotating loading messages until `/api/chat` responds.
   - Parsed slides appear in Slide panel; thumbnails become selectable.
3. **Refine slides**
   - Select contiguous slides via ribbon or tile button.
   - Provide instructions (e.g., “Condense slides 2-3 into a single chart”). Selection is included in the next `/api/chat` call.
   - `ReplacementFeedback` summarizes how many slides changed.
4. **Manual adjustments**
   - Edit HTML via modal (validated to ensure `.slide` class).
   - Duplicate/delete/reorder as needed; backend stays source of truth.
5. **QA raw output**
   - Compare raw HTML render vs parsed slides to troubleshoot parser drift.

---

## Notes for Contributors & AI Agents

- **Single source of truth:** Treat backend responses as canonical. Even after optimistic UI updates, fetch the latest deck to keep `slide_count`, CSS, and scripts aligned.
- **Selection integrity:** Always preserve contiguity when you programmatically set selections (use `setSelection`). Non-contiguous ranges break server-side replacement logic.
- **Script safety:** `SlideTile` wraps deck-level scripts in a `try/catch` so charts that refer to missing canvases fail gracefully. Reuse this pattern if you add other embed surfaces.
- **Validation:** `HTMLEditorModal` requires at least one `<div class="slide">`. If backend contract changes, update this validator simultaneously.
- **Future session support:** `api.ts` is prepped for a `session_id`. Thread this through props/state rather than reading globals so multiple sessions can coexist later.
- **Loading UX:** `getRotatingLoadingMessage` ensures the UI feels alive even for long model calls. Extend `LOADING_MESSAGES` instead of creating new timers elsewhere.

---

## Extending / Debugging Checklist

1. **Need new backend call?** Add it to `src/services/api.ts`, type the response in `src/types`, and keep `ApiError` semantics consistent.
2. **Adding shared state?** Prefer contexts/hooks similar to `SelectionContext` to avoid prop drilling between Chat and Slide panels.
3. **Instrumenting events?** `ChatPanel` is the choke point for AI interactions; emit analytics/logging there.
4. **AI agent automation:** When scripting UI flows, favor SelectionRibbon for multi-select (keyboard accessible) and obey view toggles (`viewMode`).
5. **Docs sync:** Update this file and `frontend/README.md` if you introduce new paradigms (e.g., multi-session tabs, new panels).

With these pieces you should be able to reason about the entire frontend stack and confidently extend it or plug new backend capabilities into the UI.

