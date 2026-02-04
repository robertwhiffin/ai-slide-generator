# Frontend System Overview

How the React/Vite frontend is structured, how it communicates with backend APIs, and the concepts needed to extend or operate the UI.

---

## Stack & Entry Points

- **Tooling:** Vite + React + TypeScript, Tailwind utility classes, `@dnd-kit` for drag/drop, `@monaco-editor/react` for HTML editing, standard Fetch for API calls.
- **Entrypoint:** `src/main.tsx` injects `&lt;App /&gt;` into `#root`. `src/App.tsx` wraps the tree in `ProfileProvider`, `SessionProvider`, `GenerationProvider`, `SelectionProvider` and renders `AppLayout`.
- **Env configuration:** `src/services/api.ts` reads `import.meta.env.VITE_API_URL` (defaults to `http://localhost:8000` in dev, relative URLs in production).

---

## High-Level Layout (`src/components/Layout/AppLayout.tsx`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Header: title + session metadata + navigation                         │
│ [Generator] [History] [Profiles] [Deck Prompts] [Slide Styles] [Help] │
├──────────────┬──────────────┬─────────────────────────────────────────┤
│ Chat Panel   │ Selection    │ Slide Panel                             │
│ (32% width)  │ Ribbon       │ (flex-1)                                │
│              │ (fixed 256px)│                                         │
└──────────────┴──────────────┴─────────────────────────────────────────┘
```

### View Modes

The app has six view modes controlled by navigation buttons:
- **Generator** (`main`): The primary slide generation interface
- **History**: Session list and restore functionality
- **Profiles**: Configuration profile management
- **Deck Prompts**: Presentation template library management
- **Slide Styles**: Visual style library management (typography, colors, layout)
- **Help**: Documentation and usage guide

- **ChatPanel** owns chat history and calls backend APIs to generate or edit slides.
- **SelectionRibbon** mirrors the current `SlideDeck` with dual interaction:
  - **Click slide preview** – scrolls the main SlidePanel to that slide
  - **Click checkbox** – toggles slide selection for chat context (contiguous only)
- **SlidePanel** shows parsed slides, raw HTML render, or plain HTML text; exposes per-slide actions (edit, delete, reorder). Accepts `scrollToSlide` prop to navigate to a specific slide.
- **AppLayout** manages shared state:
  - `slideDeck: SlideDeck | null` – parsed slides plus CSS/script metadata
  - `rawHtml: string | null` – exact HTML from the AI for debugging views
  - `scrollTarget: { index, key } | null` – coordinates ribbon-to-panel navigation

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
  slides: Slide[];
}

interface Slide {
  index: number;
  slide_id: string;
  html: string;
  scripts: string;
  content_hash?: string;              // SHA256 hash of normalized HTML (for verification persistence)
  verification?: VerificationResult;  // LLM as Judge verification (auto-verified, persisted by content hash)
}
```

Slides are HTML snippets embedded in iframes for preview. The optional `verification` field stores auto-verification accuracy checks using MLflow's LLM as Judge (runs automatically when slides are generated or edited).

### 3. Selection Context (`src/contexts/SelectionContext.tsx`)

- Stores `selectedIndices` and corresponding `Slide[]`
- Enforces contiguous selections via `utils/slideReplacements.ts::isContiguous`
- Shared by Chat + Slide panels so the assistant receives focused context

### 4. Generation Context (`src/contexts/GenerationContext.tsx`)

- Tracks `isGenerating` boolean for navigation locking
- Set by `ChatPanel` during streaming, consumed by `AppLayout`
- Disables navigation buttons, profile selector, and session actions during generation

### 5. Version Check (`src/hooks/useVersionCheck.ts`)

Checks for app updates on load and displays a banner if a newer version is available on PyPI:

```typescript
const { updateAvailable, latestVersion, updateType, dismiss } = useVersionCheck();
```

- **Checks once on app load** - calls `/api/version/check` (backend caches PyPI responses for 1 hour)
- **Classifies update type:**
  - `patch`: Only patch version changed (e.g., 0.1.19 → 0.1.20) - redeploy the app
  - `major`: Minor or major version changed (e.g., 0.1.x → 0.2.x) - run `tellr.update()`
- **Dismissable per session** - uses sessionStorage so banner reappears on next visit
- **Fails silently** - version check is non-critical, errors don't affect app functionality

The `UpdateBanner` component displays at the top of the app with different messaging based on update type.

### 5. Chat Responses (`src/types/message.ts`)

- `ChatResponse` includes messages, `slide_deck`, `raw_html`, and optional `replacement_info`
- `ReplacementInfo` rendered via `ReplacementFeedback` to show slide changes

### 6. View Modes

Parsed tiles, rendered raw HTML (`iframe`), and raw HTML text (`<pre>`). Users can compare parser output vs. model output.

### 7. Profile Creation Wizard (`src/components/config/ProfileCreationWizard.tsx`)

Profile creation uses a 5-step wizard that collects essential configuration. LLM and MLflow settings use backend defaults.

**Wizard Steps:**
1. **Basic Info** - Profile name and description
2. **Genie Space** - Optional data source selection with description (enables data queries)
3. **Slide Style** - Required visual appearance selection
4. **Deck Prompt** - Optional presentation template selection
5. **Review** - Summary of settings before creation

**Genie Space is Optional:**
- Profiles without a Genie space run in **prompt-only mode**
- The agent generates slides purely from conversation without data queries
- A Genie space can be added later from the profile settings

**Default Values (applied automatically by backend):**
- **LLM**: `databricks-claude-sonnet-4-5`, temperature 0.7, max tokens 60000
- **MLflow**: `/Workspace/Users/{username}/ai-slide-generator`

**Key behaviors:**
- The "Next" button is disabled until required fields are completed (Genie is skippable)
- Profile is created with all configurations in a single transaction via `POST /api/settings/profiles/with-config`
- LLM, MLflow, and Genie settings can be customized after profile creation in the profile settings
- After creation, the new profile is automatically set as default and loaded

### 8. Deck Prompt Library (`src/components/config/DeckPromptList.tsx`)

Deck Prompts are reusable presentation templates that guide AI slide generation:

```typescript
interface DeckPrompt {
  id: number;
  name: string;              // e.g., "Quarterly Business Review"
  description: string | null;
  category: string | null;   // e.g., "Report", "Summary", "Analysis"
  prompt_content: string;    // Instructions for the AI
  is_active: boolean;
  created_by: string | null;
}
```

**How they work:**
1. Prompts are managed globally via the **Deck Prompts** page
2. Each Profile can select one prompt via the **Deck Prompt** tab in profile settings
3. When generating slides, the selected prompt content is prepended to the system prompt
4. User chat messages combine with the deck prompt for context-aware generation

### 9. Slide Style Library (`src/components/config/SlideStyleList.tsx`)

Slide Styles control the visual appearance of generated slides:

```typescript
interface SlideStyle {
  id: number;
  name: string;              // e.g., "Databricks Brand"
  description: string | null;
  category: string | null;   // e.g., "Brand", "Minimal", "Dark"
  style_content: string;     // Typography, colors, layout rules
  is_active: boolean;
  created_by: string | null;
}
```

**How they work:**
1. Styles are managed globally via the **Slide Styles** page
2. Each Profile can select one style via the **Slide Style** tab in profile settings
3. When generating slides, the selected style content is included in the system prompt
4. Styles define typography (fonts, sizes), colors (brand palette, accents), and layout rules

**Profile Configuration Tabs:**
- **Deck Prompt**: Select a presentation template (WHAT to create)
- **Slide Style**: Select visual appearance (HOW it should look)
- **Advanced**: Edit system prompts directly (debug mode only - hidden by default)

---

## Component Responsibilities

| Path | Responsibility | Backend Touchpoints |
|------|----------------|---------------------|
| `src/components/ChatPanel/ChatPanel.tsx` | Sends prompts via SSE or polling, displays real-time events, loads persisted messages | `api.sendChatMessage`, `api.getSession` |
| `src/components/ChatPanel/ChatInput.tsx` | Textarea with selection badge when context exists | None (props only) |
| `src/components/ChatPanel/MessageList.tsx` & `Message.tsx` | Renders conversation, collapses HTML/tool outputs | None |
| `src/components/SlidePanel/SlidePanel.tsx` | Hosts drag/drop, tabs, per-slide CRUD, auto-verification trigger for unverified slides | `api.getSlides`, `api.reorderSlides`, `api.updateSlide`, `api.deleteSlide`, `api.verifySlide` |
| `src/components/SlidePanel/SlideTile.tsx` | Slide preview, selection button, editor modal, Genie source data button, displays verification badge | Prop callbacks to `SlidePanel`, `api.getGenieLink` |
| `src/components/SlidePanel/VerificationBadge.tsx` | Rating badge, details popup, feedback UI (thumbs up/down), manual re-verify option | `api.verifySlide`, `api.submitVerificationFeedback` |
| `src/components/SlidePanel/SlidePanel.tsx` | Hosts drag/drop, tabs, per-slide CRUD, optimize layout handler | `api.getSlides`, `api.reorderSlides`, `api.updateSlide`, `api.deleteSlide`, `api.sendChatMessage` |
| `src/components/SlidePanel/SlideTile.tsx` | Slide preview, selection button, editor modal trigger, optimize layout button | Prop callbacks to `SlidePanel` |
| `src/components/SlidePanel/HTMLEditorModal.tsx` | Visual slide editor with tree-based text editing. Parses any HTML structure into editable nodes. Charts shown read-only. | Calls `api.updateSlide` then `api.getSlides` |
| `src/components/SlidePanel/visualEditor.types.ts` | TypeScript interfaces for EditableNode and TreeState | None |
| `src/components/SlidePanel/treeParser.ts` | HTML parsing utilities: buildEditableTree, applyTextChange, buildPreviewHtml | None |
| `src/components/SlidePanel/ElementTreeView.tsx` | Tree view component with collapsible nodes and inline text editing | None |
| `src/components/SlidePanel/VisualEditorPanel.tsx` | Split-pane visual editor with element tree and live preview | None |
| `src/components/SlidePanel/SelectionRibbon.tsx` + `SlideSelection.tsx` | Thumbnail strip with dual interaction: preview click navigates main panel, checkbox toggles selection for chat context | `onSlideNavigate` callback to `AppLayout`, updates `SelectionContext` |
| `src/hooks/useKeyboardShortcuts.ts` | `Esc` clears selection globally | None |
| `src/utils/loadingMessages.ts` | Rotating messages during LLM calls | None |
| `src/components/common/Tooltip.tsx` | Lightweight hover tooltip wrapper using Tailwind; appears instantly on hover | None |
| `src/components/config/ProfileCreationWizard.tsx` | 4-step wizard for profile creation; LLM and MLflow use backend defaults | `configApi.createProfileWithConfig` |
| `src/components/config/DeckPromptList.tsx` | Deck prompt library management: list, create, edit, delete prompts | `configApi.listDeckPrompts`, `configApi.createDeckPrompt`, `configApi.updateDeckPrompt`, `configApi.deleteDeckPrompt` |
| `src/components/config/DeckPromptForm.tsx` | Modal form for creating/editing deck prompts with Monaco editor | None (callback props) |
| `src/components/config/DeckPromptSelector.tsx` | Profile configuration tab for selecting a deck prompt from the library | `configApi.listDeckPrompts`, `configApi.updatePromptsConfig` |
| `src/components/config/SlideStyleList.tsx` | Slide style library management: list, create, edit, delete styles | `configApi.listSlideStyles`, `configApi.createSlideStyle`, `configApi.updateSlideStyle`, `configApi.deleteSlideStyle` |
| `src/components/config/SlideStyleForm.tsx` | Modal form for creating/editing slide styles with Monaco editor | None (callback props) |
| `src/components/config/SlideStyleSelector.tsx` | Profile configuration tab for selecting a slide style from the library | `configApi.listSlideStyles`, `configApi.updatePromptsConfig` |
| `src/components/config/AdvancedSettingsEditor.tsx` | Power-user interface for editing system prompts (debug mode only) | `configApi.updatePromptsConfig` |
| `src/components/UpdateBanner/UpdateBanner.tsx` | Displays update notification when new version available; different messaging for patch vs major updates | None (props only) |
| `src/hooks/useVersionCheck.ts` | Checks PyPI for new versions on app load; returns update availability and type | `GET /api/version/check` |

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

### Selecting Slides and Navigation

- **Ribbon navigation:** Clicking a slide preview in `SelectionRibbon` scrolls `SlidePanel` to that slide via `scrollToSlide` prop
- **Ribbon selection:** Clicking a checkbox in `SelectionRibbon` toggles that slide's selection for chat context
- `SelectionRibbon` recomputes on deck changes
- Non-contiguous selections show warning and are ignored
- `SlideTile` action button marks single slides
- `SelectionBadge` in `ChatInput` shows current range with clear option

### Slide Operations

| Operation | API Call | Notes |
|-----------|----------|-------|
| **Reorder** | `api.reorderSlides(newOrder, sessionId)` | Optimistic UI with rollback on failure |
| **Delete** | `api.deleteSlide(index, sessionId)` | Returns full updated deck |
| **Edit HTML** | `api.updateSlide(index, html, sessionId)` | Validates `.slide` wrapper |
| **Optimize Layout** | `api.sendChatMessage(sessionId, message, slideContext)` | Sends optimization prompt with slide context; preserves chart scripts automatically via backend |

### Optimize Layout Feature

The optimize layout feature allows users to automatically fix slide overflow issues while preserving chart functionality:

1. **Trigger**: Click the optimize icon (purple maximize button) on any slide tile
2. **Process**: 
   - Sends chat message "optimize layout not to overflow" with explicit instructions to preserve all `<canvas>` elements and their IDs
   - Includes slide HTML as context
   - Backend preserves original scripts for matching canvas IDs during replacement
3. **Result**: 
   - Slide layout is optimized to prevent overflow
   - Chart elements and their IDs are preserved
   - Original chart scripts are automatically re-attached if canvas IDs match
   - Loading state shown during optimization

The optimization prompt explicitly instructs the agent to:
- Preserve ALL `<canvas>` elements exactly (no modification, removal, or ID changes)
- Only adjust spacing, padding, margins, font sizes, and positioning of non-chart elements
- Maintain 1280x720px slide dimensions
- Not modify any chart-related HTML structure

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
| `submitChatAsync` | POST | `/api/chat/async` | `{ session_id, message, slide_context? }` | `{ request_id }` |
| `pollChat` | GET | `/api/chat/poll/{id}` | query: `after_message_id` | `PollResponse` |
| `sendChatMessage` | – | – | Auto-selects SSE or polling | Cancel function |
| `healthCheck` | GET | `/api/health` | – | `{ status }` |
| `getSlides` | GET | `/api/sessions/{id}/slides` | – | `{ session_id, slide_deck }` |
| `reorderSlides` | PUT | `/api/slides/reorder` | `{ session_id, new_order }` | `SlideDeck` |
| `updateSlide` | PATCH | `/api/slides/{index}` | `{ session_id, html }` | `Slide` |
| `deleteSlide` | DELETE | `/api/slides/{index}` | query: `session_id` | `SlideDeck` |
| `updateSlideVerification` | PATCH | `/api/slides/{index}/verification` | `{ session_id, verification }` | `SlideDeck` |

### Verification Endpoints (LLM as Judge)

| Method | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `verifySlide` | POST | `/api/verification/{index}` | `{ session_id }` | `VerificationResult` |
| `submitVerificationFeedback` | POST | `/api/verification/{index}/feedback` | `{ session_id, is_positive, rationale?, trace_id? }` | `{ status, message, linked_to_trace }` |
| `getGenieLink` | GET | `/api/verification/genie-link` | query: `session_id` | `{ has_genie_conversation, url?, ... }` |

### Version Check Endpoint

| Method | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `checkVersion` | GET | `/api/version/check` | – | `{ installed_version, latest_version, update_available, update_type }` |

The version check endpoint compares the installed `databricks-tellr-app` version against PyPI. The `update_type` is either `"patch"` (redeploy the app) or `"major"` (run `tellr.update()`). Backend caches PyPI responses for 1 hour.

### Error Handling

Errors bubble up as `ApiError` (status + message). Common statuses:
- **409 Conflict** – session is processing another request (retry after delay)
- **404 Not Found** – session or resource doesn't exist
- **400 Bad Request** – validation failure (e.g., non-contiguous indices)

---

## User Flow Reference

### Profile Creation
1. **Open Profiles page** – Click "Profiles" in navigation
2. **Start wizard** – Click "Create Profile" button
3. **Basic Info** – Enter profile name and optional description
4. **Genie Space** – Select data source and provide AI description
5. **LLM Settings** – Configure model (defaults pre-populated)
6. **MLflow** – Review experiment path (auto-populated with username)
7. **Deck Prompt** – Optionally select a presentation template
8. **Review & Create** – Confirm settings and create
9. **Auto-activate** – New profile is automatically set as default and loaded

### Slide Generation
1. **Start session** – Load app, session created on first interaction
2. **Generate baseline deck** – Enter prompt, chat panel shows loading, slides appear
3. **Auto-verification** – LLM as Judge automatically verifies each slide against Genie source data
4. **Navigate slides** – Click slide preview in ribbon to scroll main panel to that slide
5. **Review verification** – Click verification badge for details, provide feedback (👍/👎)
6. **Refine slides** – Use checkbox in ribbon to select contiguous slides for chat context, provide instructions
7. **Manual adjustments** – Edit HTML via modal, delete/reorder (edited slides auto-re-verify)
8. **View source data** – Click database icon on slide to open Genie conversation
9. **QA raw output** – Compare raw HTML render vs parsed slides

---

## Notes for Contributors & AI Agents

- **Single source of truth:** Backend responses are canonical. Refetch after mutations.
- **Selection integrity:** Always preserve contiguity when setting selections programmatically.
- **Script safety:** `SlideTile` wraps scripts in try/catch for graceful chart failures.
- **Script preservation:** Backend automatically preserves chart scripts when canvas IDs match during slide replacement (e.g., optimize layout).
- **Visual editing:** `HTMLEditorModal` provides tree-based text editing without HTML knowledge. Charts (canvas elements) are read-only to preserve Chart.js functionality.
- **Session scope:** All operations require valid session ID. Handle 409 with retry/wait UX.
- **Loading UX:** `getRotatingLoadingMessage` keeps UI responsive during long LLM calls.
- **Optimize layout:** Preserves chart functionality by maintaining canvas IDs and automatically re-attaching scripts.

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
- [LLM as Judge Verification](llm-as-judge-verification.md) – Auto slide accuracy verification and human feedback collection
- [Real-Time Streaming](real-time-streaming.md) – SSE events and conversation persistence
- [Multi-User Concurrency](multi-user-concurrency.md) – session locking and async handling
- [Slide Parser & Script Management](slide-parser-and-script-management.md) – HTML parsing and Chart.js reconciliation
