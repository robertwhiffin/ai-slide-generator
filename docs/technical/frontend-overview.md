# Frontend System Overview

How the React/Vite frontend is structured, how it communicates with backend APIs, and the concepts needed to extend or operate the UI.

---

## Stack & Entry Points

- **Tooling:** Vite + React + TypeScript, Tailwind utility classes, `@dnd-kit` for drag/drop, `@monaco-editor/react` for HTML editing, standard Fetch for API calls.
- **Entrypoint:** `src/main.tsx` wraps `<App />` in `<BrowserRouter>` and injects into `#root`. `src/App.tsx` checks setup status via `/api/setup/status` and shows `WelcomeSetup` if not configured; otherwise wraps the tree in `SessionProvider`, `GenerationProvider`, `SelectionProvider`, `ToastProvider`, `AgentConfigProvider` and defines routes via React Router v7 — each route renders `AppLayout` (which adds `ProfileProvider`) with `initialView` and optional `viewOnly` props.
- **Env configuration:** `src/services/api.ts` reads `import.meta.env.VITE_API_URL` (defaults to `http://127.0.0.1:8000` in dev, relative URLs in production).

---

## High-Level Layout (`src/components/Layout/AppLayout.tsx`)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Header: title + session metadata + navigation                         │
│ [New Session] [My Sessions] [Profiles] [Deck Prompts] [Slide Styles]        │
│ [Design Systems] [Images] [Help]                                            │
├──────────────┬──────────────┬─────────────────────────────────────────┤
│ Chat Panel   │ Selection    │ Slide Panel                             │
│ (32% width)  │ Ribbon       │ (flex-1)                                │
│              │ (fixed 256px)│                                         │
└──────────────┴──────────────┴─────────────────────────────────────────┘
```

### View Modes & URL Routing

Each page has a dedicated URL. Navigation buttons use `useNavigate()` to change routes. Session routes (`/sessions/:id/edit`, `/sessions/:id/view`) load session data from URL parameters. See [URL Routing](url-routing.md) for full details.

- **New Session** (`/sessions/:id/edit`): The primary slide generation interface
- **Viewer** (`/sessions/:id/view`): Read-only presentation viewer (chat disabled, editing disabled)
- **My Sessions** (`/history`): Session list, restore, rename, delete, and **duplicate** deck (opens the new copy; shared tab does the same after duplicate)
- **Recent Decks** (sidebar): Ten most recent decks via `GET /api/sessions?deck_only=true`
- **Profiles** (`/profiles`): Saved configuration snapshots
- **Deck Prompts** (`/deck-prompts`): Presentation template library management
- **Slide Styles** (`/slide-styles`): Visual style library management (typography, colors, layout)
- **Design Systems** (`/design-systems`): Brand bundle library — tokens, fonts, assets, named templates. See [Design System Library](design-system-library.md)
- **Images** (`/images`): Image library management
- **Help** (`/help`): Documentation and usage guide
- **Admin** (`/admin`): Wrapped in `<RequireAdmin>`. Six tabs — Usage, Feedback, Google Slides, Design System, Slide Style, Judge. The Design System and Slide Style tabs are the **only** place the workspace-wide org default is set
- **Feedback redirect** (`/feedback`): Redirects to `/admin`

The landing page (`/`) now shows the generator directly in pre-session mode.

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

Every user interaction is scoped to a session. `SessionContext` provides session state and the `api.ts` module tracks `currentSessionId`:

```typescript
// src/contexts/SessionContext.tsx
createNewSession()   // Generates local UUID, updates context (callers persist to DB)
switchSession(id)    // Loads existing session from database

// src/services/api.ts
api.setCurrentSessionId()  // Set active session for API calls
api.createSession({ sessionId, title })  // Persist session to database
```

All API calls that modify state require `session_id`. Sessions are persisted to the database immediately when created via the "New Session" button (before navigation). Empty sessions are automatically cleaned up when the next session is created.

### 2. Slide Deck Contract (`src/types/slide.ts`)

```typescript
interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: Slide[];
  html_content?: string;
  version?: number;       // Server-side optimistic lock version from SessionSlideDeck
  created_by?: string;
  created_at?: string;
  modified_by?: string;
  modified_at?: string;
}

interface Slide {
  index: number;
  slide_id: string;
  html: string;
  scripts: string;
  content_hash?: string;              // SHA256 hash of normalized HTML (for verification persistence)
  verification?: VerificationResult;  // LLM as Judge verification (auto-verified, persisted by content hash)
  created_by?: string;
  created_at?: string;   // ISO 8601 timestamp
  modified_by?: string;
  modified_at?: string;  // ISO 8601 timestamp
}
```

Slides are HTML snippets embedded in iframes for preview. The optional `verification` field stores auto-verification checks (**MLflow LLM-as-judge** by default; **Direct** ChatDatabricks optional via Admin) against tool/source data from the session.

### 3. Selection Context (`src/contexts/SelectionContext.tsx`)

- Stores `selectedIndices` and corresponding `Slide[]`
- Enforces contiguous selections via `utils/slideReplacements.ts::isContiguous`
- Shared by Chat + Slide panels so the assistant receives focused context

### 4. Generation Context (`src/contexts/GenerationContext.tsx`)

- Tracks `isGenerating` boolean for navigation locking
- Set by `ChatPanel` during streaming, consumed by `AppLayout`
- Disables navigation buttons, AgentConfigBar, and session actions during generation

### 4b. Agent Config Context (`src/contexts/AgentConfigContext.tsx`)

Manages the active agent configuration (tools, slide style, deck prompt). Operates in two modes:

- **Pre-session mode** (no `/sessions/:id/` in URL): Config stored in React state + localStorage. Persists across navigation until a session is created.
- **Active session mode**: Config loaded from backend on session change. Updates synced via `PUT /api/sessions/{id}/agent-config` with optimistic updates (reverts on failure).

```typescript
// Key operations
updateConfig(config)       // Replace full agent config
addTool(tool)              // Add a Genie space or MCP server
removeTool(tool)           // Remove a tool
setStyle(styleId)          // Set slide style
setDeckPrompt(promptId)    // Set deck prompt
saveAsProfile(name, desc)  // Save current config as a named profile (active session only)
loadProfile(profileId)     // Load a profile's config into current session
```

Used by: `AgentConfigBar`, `ChatPanel`.

**Default resolution:** When no stored config exists (new session or first visit), the context resolves defaults for each config field.

| Config Field | localStorage Key | Priority |
|---|---|---|
| Profile | `userDefaultProfileId` | localStorage > server `is_my_default` > server `is_default` |
| Deck Prompt | `userDefaultDeckPromptId` | localStorage only (no server-side default) |

Users set their personal defaults via the "Set as default" button on each settings page. The preference is per-browser and is not synced to the backend.

**The visual-style slot is mutually exclusive, but resolution is entry-path dependent.** A design system and a slide style cannot both apply; when both are present the design system wins and the style is dropped — enforced in the model serializer, the column bind, and a database `BEFORE INSERT OR UPDATE` trigger.

There is **no ordering over the sources that holds on every path.** The context runs a decision tree per entry path, and each returns early: the guards distinguish a field the caller omitted from one it set to `null`, and they read persisted provenance (`style_source`) rather than re-deriving it by comparing an id to the current default. The browser's paths:

| Path | Behaviour |
|---|---|
| **Fresh pre-session surface** | No `localStorage` mirror. Load the selected profile, stamp its provenance, then resolve through `withResolvedStyleSource(config, { isNewSurface: true })`. The session `GET` passes the same flag when the server holds no config for that session. |
| **Stored mirror / restored surface** | The mirror's **existence**, never its content, selects this path — an explicit "Design System: None" is byte-identical to the first-paint placeholder. Resolves without `isNewSurface`, so an absent `style_source` is preserved as the user's choice. Runs only when `design_system_id` or `deck_prompt_id` is missing, and a mirror stamped `'seeded'` clears both guards — with an empty design-system slot it still picks up a later org default. |
| **Default profile** | `profileStyleSource` stamps `'user'` for a profile whose `created_by` is not `system`, or a system profile re-pointed at another style; `'seeded'` only for the server's own profile still holding the style the server seeds. A `'user'` stamp short-circuits every lower default. |
| **New session** | Seeding is the server's (`_apply_org_default_style_source`), per field, and only for fields absent from `model_fields_set`. An explicit `null` is a choice and is left alone. `template_id` is stripped by `_without_template_pin`. |
| **Existing session** | The persisted slot is used as stored. The `GET` sanitizes stale design-system and template **pins** and flags a cleared design system as `design_system_unavailable`; `withResolvedStyleSource` runs only when the server holds no config for the session. |

`withResolvedStyleSource` returns at the first matching guard:

1. `style_source === 'user'` → unchanged (covers "neither a design system nor a style").
2. `!isNewSurface && style_source == null` → unchanged.
3. `design_system_id != null` → unchanged.
4. Personal default design system → claim the slot, clear `slide_style_id`, stamp `'user'`.
5. `slide_style_id != null` **and** a personal default style exists → claim the slot, stamp `'user'`. **Returns before the org default design system is resolved**, so a personal style default can suppress org-default design-system seeding.
6. Org default design system → claim the slot, clear `slide_style_id`, stamp `'seeded'`.
7. Otherwise personal default style (`'user'`), else the server's `is_default` — falling back to `is_system` — style (`'seeded'`).

**Clearing a personal default releases the config slot, not just the localStorage key.** Removing only the key would leave the resolved id in the mirrored config, so guard 3 would short-circuit and the preference below would never take effect. `setUserDefaultDesignSystem(null)` writes `design_system_id: null`, `template_id: null`, `slide_style_id: userPreferredStyleId()` and `style_source: 'user'` **before** dropping the key, so a failed release keeps the preference and a later attempt can retry. The Clear button does not stay visible through that failure — `DesignSystemLibrary` clears its local `userDefaultId` state before awaiting the release and renders the button from that state, so it returns only on remount, re-read from the surviving key. It does **not** rerun lower-default resolution on that surface — the surface now carries `style_source: 'user'`.

**Personal defaults are invisible to MCP.** `create_deck` cannot read per-user localStorage. An explicit `design_system_id` wins; otherwise an explicit `slide_style_id` suppresses implicit org-default design-system seeding; otherwise the org default design system, then the tellr-configured default slide style. Flipping the admin choice therefore affects MCP-initiated decks with no explicit source immediately. For a durable, cross-browser personal default, save a profile carrying the design system and set that profile as your default.

**Server-side, `agent_factory` is a branch, not a fallthrough chain.** It selects the design-system branch when `design_system_id` is present, otherwise the slide-style branch when `slide_style_id` is present. Either lookup is filtered on `is_active = true`, and **a miss leaves the hardcoded `DEFAULT_SLIDE_STYLE`** — an inactive design system does not fall through to the deck's slide style, because that branch is an `elif` and is never evaluated. The constant is not a database row. See [Design System Library §4](./design-system-library.md) for the full cross-surface reference.

### 4c. Profile Context (`src/contexts/ProfileContext.tsx`)

Manages profile CRUD operations and the profile list. Wraps inside `AppLayout` (not app-level) because it's only needed by the profile management page.

```typescript
// Key operations
reload()                   // Refresh profile list from backend
createProfile(data)        // Create new profile
updateProfile(id, data)    // Update profile metadata (name, description)
deleteProfile(id)          // Delete a profile
setDefaultProfile(id)      // Mark profile as default
loadProfile(id)            // Load profile and trigger hot-reload
```

Used by: `ProfileList` on the `/profiles` page.

**How they interact:** `AgentConfigContext` handles the active session's tool/style/prompt configuration. `ProfileContext` handles profile metadata (names, defaults, CRUD). Users save configs as profiles via `AgentConfigContext.saveAsProfile()` and browse/manage profiles via `ProfileContext`.

### 5. Version Check (`src/hooks/useVersionCheck.ts`)

Checks for app updates on load and displays a banner if a newer version is available on PyPI:

```typescript
const { updateAvailable, latestVersion, updateType, dismiss } = useVersionCheck();
```

- **Checks once on app load** - calls `/api/version/check` via direct `fetch` (backend caches PyPI responses for 1 hour)
- **Classifies update type:**
  - `patch`: Only patch version changed (e.g., 0.1.19 → 0.1.20) - redeploy the app
  - `major`: Minor or major version changed (e.g., 0.1.x → 0.2.x) - run `tellr.update()`
- **Dismissable per session** - uses sessionStorage so banner reappears on next visit
- **Fails silently** - version check is non-critical, errors don't affect app functionality

The `UpdateBanner` component displays at the top of the app with different messaging based on update type.

### 6. Chat Responses (`src/types/message.ts`)

- `ChatResponse` includes messages, `slide_deck`, `raw_html`, and optional `replacement_info`
- `ReplacementInfo` rendered via `ReplacementFeedback` to show slide changes

### 7. View Modes

Parsed tiles, rendered raw HTML (`iframe`), and raw HTML text (`<pre>`). Users can compare parser output vs. model output.

### 8. AgentConfigBar (`src/components/AgentConfigBar/AgentConfigBar.tsx`)

The AgentConfigBar replaces the old ProfileSelector and ProfileCreationWizard. It displays the session's current tool configuration as chips and provides controls to:
- **Add/remove tools** (Genie spaces, MCP servers) via the tool discovery endpoint
- **View Genie conversation links** directly from tool chips
- **Select slide style and deck prompt** for the session
- **Save/load profiles** as named configuration snapshots

Configuration is session-bound: changes update the session's `agent_config` JSON column via `PUT/PATCH /api/sessions/{id}/agent-config`.

### 9. Deck Prompt Library (`src/components/config/DeckPromptList.tsx`)

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
2. Each session can select one prompt via `agent_config.deck_prompt_id`
3. When generating slides, the selected prompt content is prepended to the system prompt
4. User chat messages combine with the deck prompt for context-aware generation
5. Users can set a personal default prompt via "Set as default" (stored in localStorage as `userDefaultDeckPromptId`); new sessions auto-select it

### 10. Save Points / Versioning (`src/components/SavePoints/`)

Save points allow users to preview and restore previous deck states:

```typescript
// State in AppLayout.tsx
const [versions, setVersions] = useState<SavePointVersion[]>([]);
const [currentVersion, setCurrentVersion] = useState<number | null>(null);
const [previewVersion, setPreviewVersion] = useState<number | null>(null);

// Version key forces React to re-render when switching versions
const versionKey = previewVersion 
  ? `preview-v${previewVersion}` 
  : `current-v${currentVersion || 'live'}`;
```

**Components:**
| Component | Purpose |
|-----------|---------|
| `SavePointDropdown` | Version selection dropdown showing all save points |
| `PreviewBanner` | Indigo banner with "Revert" and "Cancel" buttons during preview |
| `RevertConfirmModal` | Confirmation dialog before deleting newer versions |

**Key behaviors:**
- Save points created on the **backend** immediately after deck persistence (not driven by frontend)
- After auto-verification completes, frontend calls `api.syncVersionVerification()` to backfill scores onto the latest save point
- Maximum 40 save points per session; oldest deleted on overflow
- Preview mode disables chat input and slide editing; chat history from that version is shown
- **Duplicate** (PageHeader): copies the previewed save point when in preview; shows a confirm dialog if preview is older than the latest save point
- Restoring deletes all newer versions permanently
- `setSlideDeckGated` in AppLayout rejects stale `getSlides` responses using server deck version (`deckVersionRef`), preventing race conditions from overwriting edits
- Version dropdown auto-refreshes after any operation that bumps the deck version
- `SelectionRibbon` and `SlidePanel` use `key={versionKey}` to force remount on version preview switches

See [Save Points / Versioning](save-points-versioning.md) for full architecture.

### 11. Slide Style Library (`src/components/config/SlideStyleList.tsx`)

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
2. Each session can select one style via `agent_config.slide_style_id`
3. When generating slides, the selected style content is included in the system prompt
4. Styles define typography (fonts, sizes), colors (brand palette, accents), and layout rules
5. Users can set a personal default style via "Set as default" (stored in localStorage as `userDefaultSlideStyleId`); falls back to server `is_default` then `is_system`

---

## Component Responsibilities

| Path | Responsibility | Backend Touchpoints |
|------|----------------|---------------------|
| `src/components/ChatPanel/ChatPanel.tsx` | Sends prompts via SSE or polling, displays real-time events, loads persisted messages | `api.sendChatMessage`, `api.getSession` |
| `src/components/ChatPanel/ChatInput.tsx` | Textarea with selection badge when context exists | None (props only) |
| `src/components/ChatPanel/MessageList.tsx` & `Message.tsx` | Renders conversation, collapses HTML/tool outputs | None |
| `src/components/SlidePanel/SlidePanel.tsx` | Hosts drag/drop, tabs, per-slide CRUD, auto-verification trigger for unverified slides | `api.getSlides`, `api.reorderSlides`, `api.updateSlide`, `api.deleteSlide`, `api.verifySlide` |
| `src/components/SlidePanel/SlideTile.tsx` | Slide preview, selection button, editor modal, displays verification badge | Prop callbacks to `SlidePanel` |
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
| `src/components/AgentConfigBar/AgentConfigBar.tsx` | Session tool configuration bar; add/remove Genie spaces, select style/prompt, save/load profiles | `api.getAgentConfig`, `api.updateAgentConfig`, `api.patchTools` |
| `src/components/AgentConfigBar/GenieDetailPanel.tsx` | Inline panel for viewing and editing a Genie space description before adding or after selecting a tool; supports add and edit modes | None (callback props via `AgentConfigBar`) |
| `src/components/config/DeckPromptList.tsx` | Deck prompt library management: list, create, edit, delete prompts | `configApi.listDeckPrompts`, `configApi.createDeckPrompt`, `configApi.updateDeckPrompt`, `configApi.deleteDeckPrompt` |
| `src/components/config/DeckPromptForm.tsx` | Modal form for creating/editing deck prompts with Monaco editor | None (callback props) |
| `src/components/config/SlideStyleList.tsx` | Slide style library management: list, create, edit, delete styles | `configApi.listSlideStyles`, `configApi.createSlideStyle`, `configApi.updateSlideStyle`, `configApi.deleteSlideStyle` |
| `src/components/config/SlideStyleForm.tsx` | Modal form for creating/editing slide styles with Monaco editor | None (callback props) |
| `src/components/config/DesignSystemLibrary.tsx` | Design system library: list, personal default, delete | `/api/settings/design-systems` |
| `src/components/config/DesignSystemDetailPanel.tsx` | Detail panel: tokens, assets, plus templates and files via their own endpoints | `GET /design-systems/{id}` |
| `src/components/config/DesignSystemUploadDialog.tsx` | Bundle upload | `POST /design-systems/import` |
| `src/components/config/DesignSystemFileBrowser.tsx` | Browse and serve bundle files | `GET /design-systems/{id}/files` |
| `src/components/config/TemplateThumbnail.tsx` | Template picker image; renders a live preview when no stored thumbnail exists | `GET /templates/{id}/thumbnail` |
| `src/components/config/TemplateViewerModal.tsx` | Full-size template preview with paging | `GET /templates/{id}/source` |
| `src/components/config/templatePreviewDoc.ts` | Builds the sandboxed preview document for a template | None (pure) |
| `src/components/Admin/AdminDesignSystemDefault.tsx` | **Admin only.** Sets/clears the workspace org default | `POST /design-systems/{id}/set-default`, `/clear-default` |
| `src/components/UpdateBanner/UpdateBanner.tsx` | Displays update notification when new version available; different messaging for patch vs major updates | None (props only) |
| `src/hooks/useVersionCheck.ts` | Checks PyPI for new versions on app load via direct `fetch`; returns update availability and type | `GET /api/version/check` (direct fetch, not via `api` object) |
| `src/components/SavePoints/SavePointDropdown.tsx` | Version selection dropdown, triggers preview on selection | `api.listVersions`, `api.previewVersion` |
| `src/components/SavePoints/PreviewBanner.tsx` | Indigo banner during preview with revert/cancel actions | None (props only) |
| `src/components/SavePoints/RevertConfirmModal.tsx` | Confirmation dialog before restore (warns about version deletion) | `api.restoreVersion` |
| `src/components/Setup/WelcomeSetup.tsx` | Initial setup screen; collects workspace URL, triggers authentication, verifies configuration | `POST /api/setup/status` |
| `src/components/Admin/AdminPage.tsx` | Admin page with tabs for feedback dashboard and Google Slides OAuth configuration | None (delegates to child components) |
| `src/components/ChatPanel/PromptEditorModal.tsx` | Expanded modal editor for composing longer prompts with save and send actions | None (callback props) |
| `src/components/ChatPanel/ErrorDisplay.tsx` | Inline error banner with dismiss button, shown below chat input on API errors | None (props only) |
| `src/components/ChatPanel/LoadingIndicator.tsx` | Animated loading indicator with rotating message, shown during slide edits | None (props only) |
| `src/components/ChatPanel/SelectionBadge.tsx` | Badge in ChatInput showing the current slide selection range with a clear button | None (props only) |
| `src/components/config/GoogleSlidesAuthForm.tsx` | Google OAuth credentials upload and user authorization flow for Google Slides export | `configApi.uploadGoogleCredentials`, `configApi.getGoogleCredentialsStatus`, `configApi.deleteGoogleCredentials`, `api.getGoogleSlidesAuthUrl` |
| `src/components/config/ConfirmDialog.tsx` | Reusable confirmation dialog for destructive actions (deleting profiles, changing defaults) | None (props only) |
| `src/components/config/ContributorsManager.tsx` | Profile sharing UI; add/update/remove contributors (users/groups) with permission levels | `configApi.listContributors`, `configApi.addContributor`, `configApi.updateContributor`, `configApi.removeContributor`, `configApi.searchIdentities` |
| `src/components/DeckContributorsManager.tsx` | Deck (session) sharing UI; add/update/remove contributors with CAN_VIEW/CAN_EDIT/CAN_MANAGE permissions | `configApi.listDeckContributors`, `configApi.addDeckContributor`, `configApi.updateDeckContributor`, `configApi.removeDeckContributor` |
| `src/components/PresentationMode/PresentationMode.tsx` | Full-window slide presentation (opt-in browser fullscreen via F/toolbar) with keyboard navigation; snapshots deck on mount to immunize against parent re-renders; wraps scripts in try/catch for graceful chart failures | None (renders slide HTML in iframe) |

---

## State & Data Flow

### Initialization

1. `AppLayout` renders with `slideDeck = null`
2. `SelectionProvider` ensures any component can call `useSelection()`
3. Session created on "New Session" click: `createNewSession()` → `api.createSession({ sessionId })` → `navigate()`

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
| `createSession` | POST | `/api/sessions` | `{ session_id?, title? }` | `Session` |
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
| `listVersions` | GET | `/api/slides/versions` | query: `session_id` | `{ versions, current_version }` |
| `previewVersion` | GET | `/api/slides/versions/{n}` | query: `session_id` | `{ version_number, deck, verification_map }` |
| `restoreVersion` | POST | `/api/slides/versions/{n}/restore` | `{ session_id }` | `{ version_number, deck, deleted_versions }` |
| `createSavePoint` | POST | `/api/slides/versions/create` | `{ session_id, description }` | `{ version_number }` |
| `syncVersionVerification` | POST | `/api/slides/versions/sync-verification` | `{ session_id }` | `void` |
| `updateSlide` | PATCH | `/api/slides/{index}` | `{ session_id, html }` | `Slide` |
| `deleteSlide` | DELETE | `/api/slides/{index}` | query: `session_id` | `SlideDeck` |
| `updateSlideVerification` | PATCH | `/api/slides/{index}/verification` | `{ session_id, verification }` | `SlideDeck` |

### Verification Endpoints (LLM as Judge)

| Method | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `verifySlide` | POST | `/api/verification/{index}` | `{ session_id }` | `VerificationResult` |
| `submitVerificationFeedback` | POST | `/api/verification/{index}/feedback` | `{ session_id, is_positive, rationale?, trace_id? }` | `{ status, message, linked_to_trace }` |
| `getGenieLink` | GET | `/api/verification/genie-link` | query: `session_id` | `{ has_genie_conversation, url?, ... }` |

### Version Check

| Hook | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `useVersionCheck` | GET | `/api/version/check` | – | `{ installed_version, latest_version, update_available, update_type }` |

The version check is performed via a direct `fetch` call inside the `useVersionCheck` hook (not on the `api` object). It compares the installed `databricks-tellr-app` version against PyPI. The `update_type` is either `"patch"` (redeploy the app) or `"major"` (run `tellr.update()`). Backend caches PyPI responses for 1 hour.

### Export Endpoints

| Method | HTTP | Path | Request | Returns |
|--------|------|------|---------|---------|
| `exportPPTXAsync` | POST | `/api/export/pptx/async` | `{ session_id, slide_deck, chart_images? }` | `{ job_id, status, total_slides }` |
| `pollPPTXExport` | GET | `/api/export/pptx/poll/{id}` | – | `{ status, progress?, error? }` |
| `downloadPPTX` | GET | `/api/export/pptx/download/{id}` | – | `Blob` |
| `exportPptxHuashu` | POST | `/api/export/pptx/editable/huashu/from-html` | `{ session_id }` | `Blob` — **Primary.** The route the Export → PowerPoint button calls |
| `exportPptxEditable` | POST | `/api/export/pptx/editable/from-records` | `{ session_id, … }` | `Blob` — **Fallback** |
| `exportToGoogleSlides` | POST | `/api/export/google-slides/from-huashu` | `{ session_id }` | `{ presentation_id, presentation_url, total_slides, succeeded, failures }` |

**PPTX and Google Slides no longer share one pattern.** Both call the huashu render first, and Google Slides succeeds in a **single synchronous round-trip** carrying only `session_id`. Both also have a records-pipeline fallback, but they trigger it differently: the **Google** fallback fires only on HTTP `503` (`if (response.status === 503 && slideDeck)` in `api.ts`), while the **PPTX** fallback additionally matches the error text for the pipeline being unavailable or still installing (`SlidePanel.tsx`). Client-side chart and DOM extraction happens **only** on the fallback request, not on the primary one.

> **Historical note.** `exportPPTXAsync` / `pollPPTXExport` / `downloadPPTX` above target the LLM code-generation path (`POST /api/export/pptx/async`, `src/services/html_to_pptx.py`). That path is **superseded** and no UI surface reaches it — a repo-wide search finds no caller in the checked-in frontend. That cannot rule out an external caller invoking the route directly. The code still exists but should be treated as legacy. See [Export Features](export-features.md).

### Configuration API (`src/api/config.ts`)

The `configApi` module provides a separate API client for profile and settings management, distinct from the main `api.ts` module. It communicates with `/api/settings/*`, `/api/profiles/*`, and `/api/sessions/*/contributors` endpoints.

**Key areas:**
- **Profiles** – list, update, delete, set default, load, set global permission
- **Genie Spaces** – discover available spaces, lookup, add/update/delete per profile
- **Prompts Config** – get/update per-profile prompt settings
- **Deck Prompts Library** – CRUD for reusable presentation templates
- **Slide Styles Library** – CRUD for visual style definitions
- **Design Systems** – list, detail, bundle import, templates, assets, files, and the admin-only org default. See [Design System Library](design-system-library.md)
- **Google OAuth Credentials** – upload/check/delete app-wide Google credentials (admin)
- **Identities** – search Databricks workspace users and groups
- **Profile Contributors** – manage sharing permissions for profiles
- **Deck Contributors** – manage sharing permissions for decks (sessions)

Errors are thrown as `ConfigApiError` (status + message), separate from the main `ApiError` class.

### Error Handling

Errors bubble up as `ApiError` (status + message). Common statuses:
- **409 Conflict** – session is processing another request (retry after delay)
- **404 Not Found** – session or resource doesn't exist
- **400 Bad Request** – validation failure (e.g., non-contiguous indices)

---

## User Flow Reference

### Session Configuration
1. **Open generator** – Landing page (`/`) shows the generator directly
2. **Add tools** – Use AgentConfigBar to add Genie spaces or MCP servers
3. **Select style/prompt** – Choose a slide style and optional deck prompt
4. **Save as profile** – Optionally save the configuration as a named profile for reuse

### Slide Generation
1. **Start session** – Load app, session created on first interaction
2. **Generate baseline deck** – Enter prompt, chat panel shows loading, slides appear
3. **Auto-verification** – LLM as Judge automatically verifies each slide against Genie source data
4. **Navigate slides** – Click slide preview in ribbon to scroll main panel to that slide
5. **Review verification** – Click verification badge for details, provide feedback (👍/👎)
6. **Refine slides** – Use checkbox in ribbon to select contiguous slides for chat context, provide instructions
7. **Manual adjustments** – Edit HTML via modal, delete/reorder (edited slides auto-re-verify)
8. **View source data** – Click "Genie Data" button in header to open Genie conversation (supports multi-Genie dropdown)
9. **QA raw output** – Compare raw HTML render vs parsed slides

---

## Notes for Contributors & AI Agents

- **Single source of truth:** Backend responses are canonical. Refetch after mutations.
- **Selection integrity:** Always preserve contiguity when setting selections programmatically.
- **Script safety:** `PresentationMode` wraps scripts in try/catch for graceful chart failures.
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
- [Save Points / Versioning](save-points-versioning.md) – Complete deck state snapshots with preview and restore
- [URL Routing](url-routing.md) – Client-side routing, session URLs, shareable view links