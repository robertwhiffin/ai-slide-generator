# Frontend

React + TypeScript + Vite application for the AI Slide Generator.

## Quick Start

```bash
npm install
npm run dev     # http://localhost:5173
npm run build   # Production build → dist/
```

---

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│ Header                                                        │
├──────────────┬──────────────┬────────────────────────────────┤
│ ChatPanel    │ Selection    │ SlidePanel                     │
│ (32% width)  │ Ribbon       │ (flex-1)                       │
│              │ (256px)      │                                │
└──────────────┴──────────────┴────────────────────────────────┘
```

- **ChatPanel**: Send prompts, view messages, show replacement feedback
- **SelectionRibbon**: Pick contiguous slides for editing context
- **SlidePanel**: View/reorder/edit/duplicate/delete slides

---

## Directory Structure

```
src/
├── api/config.ts           # API base URL config
├── services/api.ts         # All backend API calls
├── types/
│   ├── slide.ts            # Slide, SlideDeck, SlideContext, ReplacementInfo
│   └── message.ts          # Message, ChatResponse, ChatMetadata
├── contexts/
│   ├── SelectionContext    # Selected slides for editing
│   ├── ProfileContext      # Active config profile
│   └── SessionContext      # Chat session state
├── hooks/
│   ├── useProfiles         # Profile CRUD operations
│   ├── useConfig           # Config form state
│   └── useKeyboardShortcuts # Global shortcuts (Esc to clear)
├── components/
│   ├── Layout/AppLayout    # Main layout, owns slideDeck + rawHtml state
│   ├── ChatPanel/          # Chat UI components
│   ├── SlidePanel/         # Slide viewing and manipulation
│   ├── config/             # Profile and settings forms
│   ├── History/            # Session history UI
│   └── Help/               # Help page (default view on app open)
└── utils/
    ├── loadingMessages.ts  # Rotating "please wait" messages
    └── slideReplacements.ts # Contiguity checks, replacement logic
```

---

## Core Data Types

**SlideDeck** (from backend):
```ts
interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;              // Deck-level styles
  external_scripts: string[]; // CDN links (Chart.js)
  scripts: string;          // Chart initialization code
  slides: Slide[];
}
```

**SlideContext** (sent with edit requests):
```ts
interface SlideContext {
  indices: number[];        // Must be contiguous
  slide_htmls: string[];    // HTML for each selected slide
}
```

**ChatResponse** (from `/api/chat`):
```ts
interface ChatResponse {
  messages: Message[];
  slide_deck: SlideDeck | null;
  raw_html: string | null;
  metadata: ChatMetadata;
  replacement_info?: ReplacementInfo;
}
```

---

## Data Flow

### Generate Slides
1. User enters prompt in `ChatInput`
2. `ChatPanel.handleSendMessage()` calls `api.sendMessage()`
3. Backend returns `ChatResponse` with new `slide_deck`
4. `AppLayout` updates `slideDeck` and `rawHtml` state
5. `SlidePanel` renders tiles, `SelectionRibbon` shows thumbnails

### Edit Slides
1. User selects slides in `SelectionRibbon` (must be contiguous)
2. `SelectionContext` stores `selectedIndices` + `selectedSlides`
3. User enters edit instruction in `ChatInput`
4. `ChatPanel` packages `SlideContext` with the request
5. Backend returns `replacement_info` with change summary
6. `ReplacementFeedback` displays "Expanded 1 → 2 slides (+1)"

### Manual Operations
- **Reorder**: Drag in `SlidePanel` → `api.reorderSlides()`
- **Edit HTML**: Modal with Monaco → `api.updateSlide()`
- **Duplicate**: `api.duplicateSlide()` → returns updated deck
- **Delete**: `api.deleteSlide()` → returns updated deck

---

## API Client (`services/api.ts`)

| Function | Method | Endpoint |
|----------|--------|----------|
| `sendMessage` | POST | `/api/chat` |
| `getSlides` | GET | `/api/slides` |
| `reorderSlides` | PUT | `/api/slides/reorder` |
| `updateSlide` | PATCH | `/api/slides/{index}` |
| `duplicateSlide` | POST | `/api/slides/{index}/duplicate` |
| `deleteSlide` | DELETE | `/api/slides/{index}` |

All functions throw `ApiError` on failure.

---

## Key Patterns

**Selection must be contiguous**: The backend requires consecutive slide indices for edits. `slideReplacements.ts::isContiguous()` validates this.

**Backend is source of truth**: After any mutation, refetch or use the returned deck. Don't trust local state alone.

**Optimistic updates with rollback**: Drag-drop reorders optimistically, reverts on API failure.

**Script safety**: `SlideTile` wraps chart scripts in try-catch to prevent render failures.

---

## Environment

Set `VITE_API_URL` to override the backend URL (default: `http://localhost:8000`).
