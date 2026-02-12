# URL Routing

Client-side routing using React Router v7, enabling bookmarkable pages, shareable session links, and standard browser navigation.

---

## Stack & Entry Points

- **Library:** `react-router-dom` v7.13 (ships its own TypeScript types)
- **Router wrapper:** `<BrowserRouter>` in `src/main.tsx`
- **Route definitions:** `AppRoutes` component in `src/App.tsx`
- **Session URL params:** `useParams()` in `src/components/Layout/AppLayout.tsx`
- **SPA catch-all:** `src/api/main.py` lines 189–201 (serves `index.html` for all non-API routes)

No backend changes were required — the existing FastAPI catch-all route already supports client-side routing.

---

## Route Map

| Path | Component | View Mode | Description |
|------|-----------|-----------|-------------|
| `/` | `AppLayout` | `help` | Landing page (same as `/help`, no redirect) |
| `/help` | `AppLayout` | `help` | Documentation and usage guide |
| `/history` | `AppLayout` | `history` | Session list and restore |
| `/profiles` | `AppLayout` | `profiles` | Profile management |
| `/deck-prompts` | `AppLayout` | `deck_prompts` | Deck prompt library |
| `/slide-styles` | `AppLayout` | `slide_styles` | Slide style library |
| `/images` | `AppLayout` | `images` | Image library |
| `/sessions/:sessionId/edit` | `AppLayout` | `main` | Full editing: chat + slides |
| `/sessions/:sessionId/view` | `AppLayout` | `main` + `viewOnly` | Read-only viewer |

---

## Architecture

### Routing Strategy

Rather than splitting `AppLayout` into separate page components, the implementation passes `initialView` and `viewOnly` props to `AppLayout` via route configuration. Each route renders the same component with different props. React's `key` prop forces full remounts when switching between routes:

```tsx
// src/App.tsx
function AppRoutes() {
  const location = useLocation();
  return (
    <Routes>
      <Route path="/" element={<AppLayout key="help" initialView="help" />} />
      <Route path="/profiles" element={<AppLayout key="profiles" initialView="profiles" />} />
      <Route path="/sessions/:sessionId/edit"
        element={<AppLayout key={`edit-${location.pathname}`} initialView="main" />} />
      <Route path="/sessions/:sessionId/view"
        element={<AppLayout key={`view-${location.pathname}`} initialView="main" viewOnly={true} />} />
      {/* ... other config page routes follow the same pattern */}
    </Routes>
  );
}
```

Session routes use `location.pathname` in the key so that navigating between different sessions (e.g., `/sessions/abc/edit` → `/sessions/def/edit`) triggers a full remount and reload.

### Provider Tree

```
BrowserRouter          (main.tsx)
└── ProfileProvider
    └── SessionProvider
        └── GenerationProvider
            └── SelectionProvider
                └── ToastProvider
                    └── AppRoutes    (route definitions)
```

`BrowserRouter` wraps the entire provider tree so that `useNavigate()` and `useLocation()` are available everywhere, including inside context providers.

### Navigation

All navigation buttons use `useNavigate()` instead of the previous `setViewMode()` state setter:

```tsx
// Before (state-based)
onClick={() => setViewMode('profiles')}

// After (URL-based)
onClick={() => navigate('/profiles')}
```

Active state detection still uses `viewMode` (set from `initialView` prop), which stays synchronized with the URL through the route definitions.

The `isGenerating` guard is preserved — all navigation buttons except "Generator" are disabled during slide generation.

---

## Key Concepts

### Session Loading from URL

When `AppLayout` mounts on a session route (`/sessions/:id/edit` or `/sessions/:id/view`), it extracts the session ID from the URL and loads the session:

```tsx
const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();

useEffect(() => {
  if (!urlSessionId || initialView !== 'main') return;
  if (urlSessionId === sessionId) return;  // Skip for newly created sessions

  const loadSession = async () => {
    try {
      const sessionInfo = await api.getSession(urlSessionId);
      // Auto-switch profile if session belongs to a different one
      if (sessionInfo.profile_id !== currentProfile?.id) {
        await loadProfile(sessionInfo.profile_id);
      }
      const { slideDeck, rawHtml } = await switchSession(urlSessionId);
      setSlideDeck(slideDeck);
      setRawHtml(rawHtml);
      setChatKey(prev => prev + 1);
    } catch {
      navigate('/help');
      showToast('Session not found', 'error');
    }
  };
  loadSession();
}, [urlSessionId]);
```

**Important invariant:** The `urlSessionId === sessionId` check prevents a redirect loop when creating new sessions. `createNewSession()` generates a local UUID and navigates to `/sessions/{newId}/edit`, but the session doesn't exist in the database yet (only persisted on first chat message). Without this guard, the session-loading effect would fire, get a 404, and redirect to `/help`.

### Last Working Session

`SessionContext` tracks `lastWorkingSessionId` in localStorage. This enables:

- **Generator button**: Returns to the last session instead of creating a new one
- **History "Back to Generator"**: Same behavior
- **HelpPage "Back" button**: Same behavior

```typescript
// SessionContext.tsx
const [lastWorkingSessionId, setLastWorkingSessionIdState] = useState<string | null>(
  () => localStorage.getItem('lastWorkingSessionId')
);
```

Updated whenever a session edit route loads:

```tsx
useEffect(() => {
  if (urlSessionId && initialView === 'main' && !viewOnly) {
    setLastWorkingSessionId(urlSessionId);
  }
}, [urlSessionId, initialView, viewOnly]);
```

### Read-Only View Mode

The `/sessions/:id/view` route passes `viewOnly={true}` to `AppLayout`, which:

| Element | Behavior |
|---------|----------|
| Chat input | Disabled via `disabled` prop (shows "Exit preview mode..." message) |
| Slide panel | Read-only via `readOnly` prop (no drag-drop, no edit, no delete) |
| Session buttons | Hidden (New, Save As, Save Points, Share) |
| Navigation | Fully functional (can browse to other pages) |
| Export | Available (PPTX export still works) |
| Chat history | Visible (shows conversation that produced the slides) |

### Share Link

A "Share" button appears in the session action bar when editing a session. It copies a view-only URL to the clipboard:

```tsx
const viewUrl = `${window.location.origin}/sessions/${urlSessionId}/view`;
await navigator.clipboard.writeText(viewUrl);
showToast('Link copied to clipboard', 'success');
```

No authentication is required for view links in the current implementation. The URL structure (`/edit` vs `/view`) supports future ACL enforcement.

### Toast Notifications

A new `ToastContext` (`src/contexts/ToastContext.tsx`) provides `showToast(message, type)` for non-blocking notifications. Used for:

- Share link copied confirmation
- Session not found errors
- Future error/success feedback

Toasts auto-dismiss after 5 seconds. Rendered at `fixed bottom-4 right-4` with `data-testid="toast"` for test targeting.

---

## Data Flow

### New Session

1. User clicks "Generator" nav button (no `lastWorkingSessionId`)
2. `createNewSession()` generates local UUID (sync, no API call)
3. `navigate(`/sessions/${newId}/edit`)` updates URL
4. `AppLayout` mounts with `initialView="main"`, `urlSessionId` = new ID
5. `urlSessionId === sessionId` → skip loading (session not in DB yet)
6. User sees empty chat + empty slide panel
7. First chat message persists session to database

### Resuming a Session

1. User opens `/sessions/abc123/edit` (bookmark, history click, or share)
2. `AppLayout` mounts, extracts `abc123` from URL
3. Session loading effect fires → `api.getSession(abc123)`
4. Profile auto-switch if needed → `loadProfile(profileId)`
5. `switchSession(abc123)` loads slides + raw HTML
6. State updates → chat panel remounts with session messages
7. `lastWorkingSessionId` updated in localStorage

### Sharing

1. User clicks "Share" in Generator header
2. View URL constructed: `origin + /sessions/{id}/view`
3. Copied to clipboard, toast shown
4. Recipient opens URL → `AppLayout` loads with `viewOnly={true}`
5. Same session loading flow, but editing controls disabled

---

## Component Responsibilities

| File | Routing Responsibility |
|------|----------------------|
| `src/main.tsx` | Wraps app in `<BrowserRouter>` |
| `src/App.tsx` | Defines all `<Route>` elements with `AppLayout` + props |
| `src/components/Layout/AppLayout.tsx` | Reads `useParams()`, loads sessions from URL, handles `viewOnly` mode, uses `useNavigate()` for all navigation |
| `src/contexts/SessionContext.tsx` | Provides `lastWorkingSessionId` (localStorage), `createNewSession()` returns ID string |
| `src/contexts/ToastContext.tsx` | New context for toast notifications (`showToast(message, type)`) |
| `src/components/ChatPanel/ChatInput.tsx` | Added `data-testid="chat-input"` for test targeting |
| `src/components/ImageLibrary/ImageLibrary.tsx` | Added `data-testid="image-library"` for test targeting |
| `src/components/History/SessionHistory.tsx` | `onSessionSelect` callback now navigates to `/sessions/{id}/edit` |

---

## Testing

26 new Playwright E2E tests across 5 spec files, all using mocked API routes (no real backend).

| Spec File | Tests | Coverage |
|-----------|-------|----------|
| `tests/routing.spec.ts` | 9 | URL → correct page content for all routes |
| `tests/session-loading.spec.ts` | 4 | Session load from URL, 404 redirect, profile auto-switch, slide count |
| `tests/navigation.spec.ts` | 5 | Nav buttons update URL, back button, Generator nav, History restore |
| `tests/viewer-readonly.spec.ts` | 4 | Disabled chat, read-only slides, hidden buttons, export available |
| `tests/share-link.spec.ts` | 4 | Share button copies view URL, toast confirmation, link opens view mode |

### Test Utilities

- **`tests/helpers/setup-mocks.ts`** — Shared mock setup extracted from `slide-generator.spec.ts`. Mocks all standard API endpoints (profiles, styles, prompts, sessions list, health check).
- **`tests/helpers/session-helpers.ts`** — Session-specific helpers: `mockSessionWithSlides(page, sessionId)`, `mockSessionNotFound(page, sessionId)`, plus test constants (`TEST_SESSION_ID`, `mockSessionDetail`, `mockSlidesResponse`).

Tests use the custom `{ test, expect }` from `./fixtures/base-test` for console error filtering, not raw `@playwright/test`.

---

## Operational Notes

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid session ID in URL | Redirect to `/help` + error toast |
| Session belongs to different profile | Auto-switch profile before loading |
| Network error during session load | Redirect to `/help` + error toast |
| No `lastWorkingSessionId` in localStorage | Generator button creates new session |

### Browser Behavior

- **Refresh**: URL preserved, session reloaded from database
- **Back/Forward**: Standard React Router history navigation
- **Bookmark**: Any URL can be bookmarked and reopened
- **Deep link**: Sharing `/sessions/:id/edit` or `/sessions/:id/view` works directly

### Configuration

No additional configuration needed. The backend's existing SPA catch-all in `src/api/main.py` serves `index.html` for all non-API routes. Vite dev server handles routing in development.

---

## Extension Guidance

- **Adding a new config page**: Add a `<Route>` in `App.tsx` with a new `initialView` value, add the view mode to the `ViewMode` type in `AppLayout.tsx`, add a nav button, and add the content section.
- **Adding authentication**: The `/edit` vs `/view` URL suffix supports ACL enforcement. Add permission checks in the session-loading effect. A future `/api/sessions/:id/permissions` endpoint can return `can_view` / `can_edit` flags.
- **URL state preservation**: Query params (e.g., `?slide=3` for deep-linking to a slide) can be added without changing the route structure.
- **Component extraction**: The current implementation keeps everything in `AppLayout` for minimal diff. A future refactor could split into `Generator`, `Viewer`, and page wrapper components as described in the design doc.

---

## Cross-References

- [Frontend Overview](frontend-overview.md) — UI/state patterns and backend touchpoints
- [Save Points / Versioning](save-points-versioning.md) — Version preview and restore (interacts with session loading)
- [Multi-User Concurrency](multi-user-concurrency.md) — Session locking (edit mode only, view mode is lock-free)
- [Design Document](../plans/2026-02-11-url-routing-design.md) — Original brainstorming and design decisions
