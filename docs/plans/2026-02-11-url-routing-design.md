# URL Routing Design

**Date**: 2026-02-11
**Status**: Design
**Branch**: TBD

## Overview

Add URL-based routing to the AI Slide Generator application to replace the current state-based view switching. This enables distinct URLs for each page, with a primary focus on making presentations shareable via link (e.g., "here's a link to the deck").

## Goals

1. **Shareable presentations**: Every deck gets a unique URL that can be shared
2. **Bookmarkable pages**: Users can bookmark specific views (profiles, sessions, etc.)
3. **Browser navigation**: Back/forward buttons work as expected
4. **ACL-ready**: URL structure supports future permission system (view vs edit)
5. **Standard web behavior**: URLs reflect application state

## Non-Goals (MVP)

- Authentication/authorization (public links for now)
- Permission system implementation (ACL structure only)
- Server-side rendering
- URL state preservation beyond route (e.g., query params for filters)

## Critical Context for Implementers

### Existing Infrastructure (DO NOT recreate)
- **SPA catch-all route already exists** in `src/api/main.py` (lines 189-201). The backend already serves `index.html` for all non-API routes. No backend changes needed.
- **ChatPanel already has a `disabled` prop** (not `readOnly`) that disables input and shows "Exit preview mode to send messages..."
- **SlidePanel already has a `readOnly` prop** that prevents mutations (reordering, deletion, editing)
- **No toast/notification system exists** — you must create one (a ToastContext + provider + component). The plan references `showToast()` throughout; this doesn't exist yet.
- **No `data-testid` attributes exist anywhere** in the frontend. They must be added to components as you implement. The existing tests use locators like `page.getByRole()` and CSS selectors like `.slide-tile`.

### Existing Test Patterns
Tests are Playwright E2E with **mocked API routes** (not real API calls). See:
- `frontend/tests/fixtures/mocks.ts` — all mock data
- `frontend/tests/fixtures/base-test.ts` — custom test fixture with console error filtering
- `frontend/tests/slide-generator.spec.ts` — example of `setupMocks()` pattern and `goToGenerator()` helper
- Tests run against Vite dev server on `localhost:3000` (configured in `playwright.config.ts`)
- API mocks intercept `http://127.0.0.1:8000/api/*` routes

### SessionContext Current Interface
```typescript
interface SessionContextType {
  sessionId: string | null;                    // Local UUID, generated on init
  sessionTitle: string | null;
  experimentUrl: string | null;
  isInitializing: boolean;
  error: string | null;
  createNewSession: () => void;                // Sync! Creates local UUID, no API call
  switchSession: (id: string) => Promise<SessionRestoreResult>;  // Loads from DB
  renameSession: (title: string) => Promise<void>;
  setExperimentUrl: (url: string | null) => void;
}
```
Key detail: `createNewSession()` is **synchronous** (generates local UUID via `crypto.randomUUID()`). Sessions are only persisted to DB on first chat message. Use the existing `switchSession()` method for loading sessions from URL params — it already validates the session exists and loads slides.

### AppLayout State That Moves to Generator
The following state lives in `AppLayout` today and must move to `Generator`:
```typescript
// Slide state
const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
const [rawHtml, setRawHtml] = useState<string | null>(null);
const [chatKey, setChatKey] = useState<number>(0);
const [scrollTarget, setScrollTarget] = useState<{ index: number; key: number } | null>(null);
const chatPanelRef = useRef<ChatPanelHandle>(null);

// Save Points state (~15 vars)
const [versions, setVersions] = useState<SavePointVersion[]>([]);
const [currentVersion, setCurrentVersion] = useState<number | null>(null);
const [previewVersion, setPreviewVersion] = useState<number | null>(null);
const [previewDeck, setPreviewDeck] = useState<SlideDeck | null>(null);
const [previewDescription, setPreviewDescription] = useState<string>('');
const [previewMessages, setPreviewMessages] = useState<Message[] | null>(null);
const [showRevertModal, setShowRevertModal] = useState(false);
const [revertTargetVersion, setRevertTargetVersion] = useState<number | null>(null);
const [pendingSavePointDescription, setPendingSavePointDescription] = useState<string | null>(null);
const [showSaveDialog, setShowSaveDialog] = useState(false);
```
Plus all their associated callback handlers (handleSlideNavigate, handleSendMessage, handleSessionRestore, handleSaveAs, handleNewSession, handlePreviewVersion, handleCancelPreview, handleRevertClick, handleRevertConfirm, handleVerificationComplete).

## URL Structure

### Routes

```
/                           → Help page (current landing behavior)
/help                       → Help page (explicit)
/history                    → Session history (user's sessions)
/profiles                   → Profile management
/deck-prompts               → Deck prompt library
/slide-styles               → Slide style library
/images                     → Image library

/sessions/:sessionId/edit   → Generator (full app: chat + slides)
/sessions/:sessionId/view   → Read-only viewer (no editing/chat input)
```

### Route Details

**Configuration pages** (`/profiles`, `/slide-styles`, etc.):
- Full-page views wrapped in `AppShell` for consistent header/nav
- Global to the app (not session-specific)
- Navigation between them updates URL
- Browser back button works naturally

**Session routes** (`/sessions/:id/edit` and `/sessions/:id/view`):
- `edit` mode: Full editing experience (chat + slides)
- `view` mode: Read-only presentation viewer
- URL suffix (`/edit` vs `/view`) sets up future ACL system
- Every session gets a unique shareable URL

**Root route** (`/`):
- Renders the HelpPage component directly (same component as `/help`, NOT a redirect)
- Both `/` and `/help` render `<HelpPage />` — no redirect, to keep URLs clean
- Nav button "Help" always navigates to `/help` (so active state detection is consistent)
- Shows instructions, users click "Generator" to start working

## User Flows

### Creating and Sharing a Presentation

1. User clicks "Generator" nav button
2. SessionContext creates new session, navigates to `/sessions/{newId}/edit`
3. User generates slides via chat
4. User clicks "Copy Share Link" button
5. Link copied: `https://app.com/sessions/{id}/view`
6. Recipient opens link → sees read-only presentation

### Browsing History and Resuming Work

1. User navigates to `/history`
2. Sees list of their previous sessions
3. Clicks a session → navigates to `/sessions/{id}/edit`
4. Generator loads that session, can continue editing

### Configuration Management

1. User is working in `/sessions/abc123/edit`
2. Clicks "Profiles" nav button → navigates to `/profiles`
3. Manages profiles, clicks "Generator" nav button
4. Returns to `/sessions/abc123/edit` (SessionContext remembers last working session)
5. Browser back button also works to return to session

## Architecture

### Router Setup

**Library**: React Router v6 (latest stable)
- Industry standard, well-documented
- Excellent TypeScript support
- Built-in hooks (`useNavigate`, `useParams`, `useLocation`)

**Integration** (`main.tsx`):
```tsx
import { BrowserRouter } from 'react-router-dom';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

**Route Configuration** (`App.tsx`):
```tsx
import { Routes, Route } from 'react-router-dom';

function App() {
  return (
    <ProfileProvider>
      <SessionProvider>
        <GenerationProvider>
          <SelectionProvider>
            <Routes>
              <Route path="/" element={<HelpPage />} />
              <Route path="/help" element={<HelpPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/profiles" element={<ProfilesPage />} />
              <Route path="/deck-prompts" element={<DeckPromptsPage />} />
              <Route path="/slide-styles" element={<SlideStylesPage />} />
              <Route path="/images" element={<ImagesPage />} />

              <Route path="/sessions/:sessionId/edit" element={<Generator />} />
              <Route path="/sessions/:sessionId/view" element={<Viewer />} />
            </Routes>
          </SelectionProvider>
        </GenerationProvider>
      </SessionProvider>
    </ProfileProvider>
  );
}
```

### Component Structure

#### Current: AppLayout (Monolithic)

`AppLayout` is a single large component (573 lines) that:
- Switches between views using `viewMode` state
- Renders different content conditionally
- Contains all layout logic in one file

#### New: Routed Components

**AppShell** - Shared header and navigation wrapper:
```tsx
interface AppShellProps {
  children: React.ReactNode;
  showSessionActions?: boolean;
  sessionId?: string;
  sessionTitle?: string;
  slideCount?: number;
  experimentUrl?: string;
}

export const AppShell: React.FC<AppShellProps> = ({
  children,
  showSessionActions = false,
  ...sessionProps
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isGenerating } = useGeneration();

  return (
    <div className="h-screen flex flex-col">
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        {/* Title, session info, navigation buttons */}
        {/* Uses useLocation() for active state */}
        {/* Uses useNavigate() for navigation */}
        {showSessionActions && <SessionActions {...sessionProps} />}
      </header>

      {children}
    </div>
  );
};
```

**Generator** - Full editing experience (replaces AppLayout "main" viewMode):
```tsx
export const Generator: React.FC = () => {
  const { sessionId } = useParams();
  const { switchSession } = useSession();
  const navigate = useNavigate();
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);
  // ... all existing state from AppLayout main mode

  // Load session from URL parameter
  useEffect(() => {
    if (sessionId) {
      switchSession(sessionId).catch(() => {
        navigate('/help');
        showToast('Session not found');
      });
    }
  }, [sessionId]);

  return (
    <AppShell
      showSessionActions={true}
      sessionId={sessionId}
      sessionTitle={sessionTitle}
      slideCount={slideDeck?.slide_count}
      experimentUrl={experimentUrl}
    >
      <div className="flex-1 flex overflow-hidden">
        <ChatPanel readOnly={false} {...chatProps} />
        <SelectionRibbon {...ribbonProps} />
        <SlidePanel readOnly={false} {...slideProps} />
      </div>
    </AppShell>
  );
};
```

**Viewer** - Read-only presentation viewer:
```tsx
export const Viewer: React.FC = () => {
  const { sessionId } = useParams();
  // Must load session data AND chat messages via API on mount
  // API calls: api.getSession(sessionId), api.getSlides(sessionId), api.getMessages(sessionId)

  return (
    <AppShell
      showSessionActions={false}
      sessionId={sessionId}
      sessionTitle={sessionTitle}
      slideCount={slideDeck?.slide_count}
    >
      <div className="flex-1 flex overflow-hidden">
        {/* NOTE: ChatPanel uses `disabled` prop (not readOnly) */}
        <ChatPanel disabled={true} previewMessages={messages} {...otherChatProps} />
        <SelectionRibbon {...ribbonProps} />
        {/* SlidePanel already supports readOnly prop */}
        <SlidePanel readOnly={true} {...slideProps} />
      </div>
    </AppShell>
  );
};
```

**Config Page Components** - Wrap existing components:
```tsx
// ProfilesPage.tsx
export const ProfilesPage: React.FC = () => {
  const handleProfileChange = () => {
    // Profile change logic
  };

  return (
    <AppShell>
      <div className="flex-1 overflow-auto bg-gray-50">
        <div className="max-w-7xl mx-auto p-6">
          <ProfileList onProfileChange={handleProfileChange} />
        </div>
      </div>
    </AppShell>
  );
};
```

Similar pattern for: `SlideStylesPage`, `DeckPromptsPage`, `ImagesPage`, `HistoryPage`, `HelpPage`

### SessionContext Updates

#### Current Behavior
- Tracks `sessionId`, `sessionTitle` in state
- `createNewSession()` generates ID, stores in state
- `switchSession(id)` loads from backend, updates state
- No URL awareness

#### New Behavior

**Interface** (changes from current marked with `// CHANGED` or `// NEW`):
```typescript
interface SessionContextType {
  sessionId: string | null;
  sessionTitle: string | null;
  experimentUrl: string | null;
  isInitializing: boolean;
  error: string | null;
  lastWorkingSessionId: string | null;              // NEW - for "Generator" nav button
  setLastWorkingSessionId: (id: string) => void;    // NEW - called by Generator on mount

  createNewSession: () => string;                     // CHANGED - now returns the new ID (still sync)
  switchSession: (id: string) => Promise<SessionRestoreResult>;  // UNCHANGED - loads session+slides from DB
  renameSession: (title: string) => Promise<void>;   // UNCHANGED
  setExperimentUrl: (url: string | null) => void;    // UNCHANGED
}

// SessionRestoreResult (unchanged from current):
interface SessionRestoreResult {
  slideDeck: SlideDeck | null;
  rawHtml: string | null;
}
```

**lastWorkingSessionId**:
- Stored in localStorage
- Updated whenever user navigates to `/sessions/:id/edit`
- Used by "Generator" nav button to return to last session
- Falls back to creating new session if no last session exists

**"Generator" nav button behavior**:
```tsx
const { lastWorkingSessionId, createNewSession } = useSession();
const navigate = useNavigate();

const handleGeneratorClick = () => {
  if (lastWorkingSessionId) {
    navigate(`/sessions/${lastWorkingSessionId}/edit`);
  } else {
    const newId = createNewSession();  // Sync - returns UUID immediately
    navigate(`/sessions/${newId}/edit`);
  }
};
```

**"New" button behavior** (in Generator header):
```tsx
const handleNewSession = () => {
  const newId = createNewSession();
  navigate(`/sessions/${newId}/edit`);
};
```

### Navigation Implementation

#### Header Navigation Buttons

**Current**: Uses `setViewMode()`:
```tsx
onClick={() => setViewMode('profiles')}
```

**New**: Uses `useNavigate()`:
```tsx
const navigate = useNavigate();
onClick={() => navigate('/profiles')}
```

**Active state** - Current uses `viewMode === 'profiles'`:
```tsx
const viewMode = 'profiles'; // state
className={viewMode === 'profiles' ? 'active' : ''}
```

**New** uses `useLocation()`:
```tsx
const location = useLocation();
const isActive = location.pathname === '/profiles';
className={isActive ? 'active' : ''}
```

**IMPORTANT - Preserve `isGenerating` guard**: Current nav buttons are disabled during generation (AppLayout lines 343-366). AppShell must replicate this:
```tsx
const { isGenerating } = useGeneration();
// All nav buttons except "Generator" are disabled when isGenerating is true
// Show "Generating..." badge when active
```

#### History Page Navigation

**Current**: Calls `handleSessionRestore(sessionId)` which loads session and sets `viewMode='main'`

**New**: Navigates directly to session URL:
```tsx
// In SessionHistory component
onClick={() => navigate(`/sessions/${sessionId}/edit`)}
```

Profile auto-switching logic (lines 73-93 in AppLayout) moves into Generator component's session load effect.

### Read-Only Mode (Viewer)

#### Component Reuse
Same components used in both Generator and Viewer:
- `ChatPanel` - uses existing `disabled` prop to disable input (NOT `readOnly` — ChatPanel uses `disabled`)
- `SlidePanel` - uses existing `readOnly` prop to disable editing (already implemented)
- `SelectionRibbon` - same behavior in both modes (no changes needed, it's view-only already)

#### Disabled Elements in View Mode
- **Chat input**: Hidden or disabled, can't send messages
- **Slide editing**: Monaco editor not accessible, can't modify HTML
- **Session actions**: "New", "Save As", "Save Points" buttons hidden
- **Drag-drop reordering**: Disabled
- **Optimize layout**: Button hidden

#### Enabled Elements in View Mode
- **Chat history**: Visible (shows how deck evolved)
- **Slide viewing**: Full deck visible, can scroll/navigate
- **Export**: PPTX export still available
- **Navigation**: Can navigate to other pages via header

### Share Link Feature

**Button placement**: In Generator header, near "Save As" button

**Implementation**:
```tsx
const handleCopyShareLink = async () => {
  const shareUrl = `${window.location.origin}/sessions/${sessionId}/view`;
  await navigator.clipboard.writeText(shareUrl);
  showToast('Share link copied to clipboard');
};

<button onClick={handleCopyShareLink}>
  Copy Share Link
</button>
```

**Behavior**:
- Generates view-only URL
- Copies to clipboard
- Shows success toast
- Link works for anyone (no auth required in MVP)

## Error Handling

### Toast/Notification System (Must Be Created)

**No toast system currently exists.** The app uses `alert()` for critical errors and inline error components. Before implementing error handling, create:

1. **`ToastContext`** + **`ToastProvider`** - Add to provider tree in `App.tsx`
2. **`Toast`** component - Dismissible notification (success/error/info variants)
3. **`useToast()`** hook - Returns `showToast(message, type)` function

Add `data-testid="toast"` to the toast component for test selectors. Keep it simple — a positioned absolute container that auto-dismisses after a few seconds.

### Invalid Session ID

**Scenario**: User navigates to `/sessions/nonexistent-id/edit` or `/view`

**Handling**:
```tsx
useEffect(() => {
  if (sessionId) {
    switchSession(sessionId).catch((error) => {
      if (error.status === 404) {
        navigate('/help');
        showToast('Session not found or has been deleted', 'error');
      } else {
        // Other errors (network, etc.)
        showToast('Failed to load session', 'error');
      }
    });
  }
}, [sessionId]);
```

### Concurrent Editing (Database Locking)

**Current behavior**: Database locking prevents concurrent edits (session_manager.py:996)

**With routing**:
- Edit mode (`/edit`): Database locking still applies
- View mode (`/view`): No locking needed, multiple viewers OK
- If session locked: Show banner "This session is being edited elsewhere"

### Loading States

**Prevent flash of wrong content**:
```tsx
const [isLoading, setIsLoading] = useState(true);

useEffect(() => {
  if (sessionId) {
    setIsLoading(true);
    switchSession(sessionId)
      .then(() => setIsLoading(false))
      .catch(() => navigate('/help'));
  }
}, [sessionId]);

if (isLoading) {
  return <LoadingSpinner />;
}

return <Generator ... />;
```

### Browser Refresh

**On `/sessions/abc123/edit` refresh**:
- React Router preserves URL
- Generator component remounts
- Loads session from URL param
- All state (conversation, slides) restored from database

## Migration & Backwards Compatibility

### Existing Sessions

**Note**: The current SessionContext doesn't persist session IDs to localStorage — it generates a fresh local UUID on each page load. Sessions are only "remembered" when explicitly restored from History. The migration concern is minimal.

**Migration on first load**: If `lastWorkingSessionId` exists in localStorage (set by the new code), redirect:
```typescript
// In a top-level component or route guard
const { lastWorkingSessionId } = useSession();
if (window.location.pathname === '/' && lastWorkingSessionId) {
  // Could optionally redirect, but landing on /help is fine per design
  // This is a nice-to-have, not critical for MVP
}
```

**Cleanup**: The old `viewMode` state was never persisted to localStorage (it was React state only), so no cleanup needed.

### Breaking Changes

**For users**:
- None - URL structure is new, existing behavior preserved
- Bookmarks to root `/` still work (lands on help)
- Sessions in localStorage automatically migrated

**For developers**:
- `viewMode` state removed - use `useLocation()` instead
- `setViewMode()` calls replaced with `navigate()`
- Tests must wrap components in `<MemoryRouter>` for routing context
- Component file structure reorganized (AppLayout split into multiple files)

## Backend Changes

### API Requirements

**No changes needed for MVP** - existing endpoints already support this:
- `GET /api/sessions/:id` - Load any session
- `GET /api/sessions/:id/messages` - Get chat history
- `POST /api/sessions` - Create new session
- All existing CRUD operations work

### Future: Access Control (ACLs)

When implementing permissions:

**New endpoint**:
```python
@router.get("/api/sessions/{session_id}/permissions")
async def get_session_permissions(session_id: str, user: User):
    return {
        "can_view": check_view_permission(session_id, user),
        "can_edit": check_edit_permission(session_id, user)
    }
```

**Generator/Viewer check permissions on load**:
- Generator: Verify `can_edit`, show error if false
- Viewer: Verify `can_view`, show error if false

### Server Configuration

**RESOLVED: No changes needed.** The SPA catch-all route already exists in `src/api/main.py` (lines 189-201):

```python
# Already implemented in main.py:
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    return FileResponse("dist/index.html")
```

This serves `index.html` for all non-API routes, which is exactly what client-side routing needs. Static assets are mounted at `/assets`. No nginx — Databricks Apps provides the reverse proxy.

**Development**: Vite dev server on port 3000, API calls go to `http://127.0.0.1:8000` via CORS. API URL configured in `frontend/src/services/api.ts` with smart env detection.

## Testing Strategy

### Test-Driven Development Approach

Following TDD principles: Write test first, watch it fail, write minimal code to pass.

### Phase 1: Core Routing Tests

**Step 1a - RED: Write E2E routing tests** (`frontend/tests/routing.spec.ts`):
```typescript
test('root path shows help page', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toContainText('Help');
});

test('navigating to /profiles shows profiles page', async ({ page }) => {
  await page.goto('/profiles');
  await expect(page.locator('h1')).toContainText('Profiles');
});

test('session edit URL loads generator', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);  // profiles, styles, etc.
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);
  await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  await expect(page.locator('[data-testid="slide-panel"]')).toBeVisible();
});

test('session view URL loads read-only viewer', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);  // profiles, styles, etc.
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);
  await expect(page.locator('[data-testid="slide-panel"]')).toBeVisible();
  // ChatPanel's input is disabled (not hidden) via `disabled` prop
  await expect(page.locator('[data-testid="chat-input"]')).toBeDisabled();
});
```

**Step 1b - Verify RED**: Run tests, watch them fail (routes don't exist yet)

**Step 1c - GREEN: Minimal router setup**:
- Install react-router-dom
- Add `<BrowserRouter>` to main.tsx
- Create basic `<Routes>` with placeholder components
- Just enough to make tests pass

**Step 1d - Verify GREEN**: All routing tests pass

### Phase 2: Session Loading Tests

**Step 2a - RED: Write session loading tests** (`frontend/tests/session-loading.spec.ts`):
```typescript
test('generator loads session from URL parameter', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);

  // Verify slides rendered (uses existing CSS selectors or new data-testid)
  await expect(page.locator('.slide-tile').first()).toBeVisible();
  // Verify slide count in header
  await expect(page.locator('text=3 slides')).toBeVisible();
});

test('invalid session ID redirects to help with error', async ({ page }) => {
  await mockSessionNotFound(page, 'nonexistent-id');
  await setupMocks(page);
  await page.goto('/sessions/nonexistent-id/edit');
  await expect(page).toHaveURL('/help');
  await expect(page.locator('[data-testid="toast"]')).toContainText('Session not found');
});

test('session loads with correct profile', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);  // profile_name: 'Sales Analytics'
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);

  await expect(page.getByRole('button', { name: /Profile:.*Sales Analytics/ })).toBeVisible();
});
```

**Step 2b - Verify RED**: Tests fail (session loading not wired to URL yet)

**Step 2c - GREEN: Wire SessionContext to URL params**:
- Update Generator to extract sessionId from `useParams()`
- Load session on mount
- Add error handling and redirect
- Profile auto-switching logic

**Step 2d - Verify GREEN**: Session loading tests pass

### Phase 3: Navigation Tests

**Step 3a - RED: Write navigation tests** (`frontend/tests/navigation.spec.ts`):
```typescript
test('clicking nav buttons changes URL', async ({ page }) => {
  await page.goto('/');
  await page.click('button:has-text("Profiles")');
  await expect(page).toHaveURL('/profiles');

  await page.click('button:has-text("Slide Styles")');
  await expect(page).toHaveURL('/slide-styles');
});

test('browser back button returns to previous page', async ({ page }) => {
  await page.goto('/help');
  await page.click('button:has-text("History")');
  await expect(page).toHaveURL('/history');

  await page.goBack();
  await expect(page).toHaveURL('/help');
});

test('clicking Generator nav returns to last session', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);
  // Wait for session to load so lastWorkingSessionId is set
  await expect(page.locator('.slide-tile').first()).toBeVisible();

  await page.click('button:has-text("Profiles")');
  await expect(page).toHaveURL('/profiles');

  await page.click('button:has-text("Generator")');
  await expect(page).toHaveURL(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);
});

test('Generator nav creates new session if no last session', async ({ page }) => {
  await setupMocks(page);
  await page.goto('/help');
  await page.click('button:has-text("Generator")');

  // Should create new UUID session and navigate there
  await expect(page).toHaveURL(/\/sessions\/[^/]+\/edit/);
  await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
});

test('History page session click navigates to edit mode', async ({ page }) => {
  await setupMocks(page);  // mockSessions contains session IDs
  await page.goto('/history');

  // Click on a session from the mock data
  const testSessionId = 'b1b4d8e3-6cf6-47cb-ad58-9fdc6ad205cc';  // From mockSessions
  await mockSessionWithSlides(page, testSessionId);
  await page.click(`text=Session 2026-01-08 20:38`);  // Title from mockSessions
  await expect(page).toHaveURL(`/sessions/${testSessionId}/edit`);
});
```

**Step 3b - Verify RED**: Tests fail (nav buttons still use setViewMode)

**Step 3c - GREEN: Replace setViewMode with navigate()**:
- Update header nav buttons to use `useNavigate()`
- Track lastWorkingSessionId in SessionContext
- Make "Generator" button navigate to last session or create new
- Update History page to navigate to session URLs

**Step 3d - Verify GREEN**: Navigation tests pass

### Phase 4: Read-Only Viewer Tests

**Step 4a - RED: Write read-only viewer tests** (`frontend/tests/viewer-readonly.spec.ts`):
```typescript
test('view mode disables chat input', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);

  await expect(page.locator('[data-testid="chat-input"]')).toBeDisabled();
  await expect(page.locator('button:has-text("Send")')).toBeDisabled();
});

test('view mode disables slide editing', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);

  // Click a slide - Monaco editor should NOT appear
  await page.click('.slide-tile:first-child');
  await expect(page.locator('.monaco-editor')).not.toBeVisible();
});

test('view mode hides session action buttons', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);

  await expect(page.locator('button:has-text("New")')).toBeHidden();
  await expect(page.locator('button:has-text("Save As")')).toBeHidden();
});

test('view mode allows export', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);

  await expect(page.locator('button:has-text("Export")')).toBeVisible();
});

test('view mode shows chat history', async ({ page }) => {
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);  // Includes messages mock
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);

  await expect(page.locator('[data-testid="chat-panel"]')).toBeVisible();
  // Messages mock returns 2 messages (user + assistant)
  await expect(page.locator('[data-testid="message"]')).toHaveCount(2);
});
```

**Step 4b - Verify RED**: Tests fail (Viewer component doesn't exist)

**Step 4c - GREEN: Create Viewer component**:
- Extract Generator component from AppLayout
- Create Viewer as similar component with readOnly props
- Wire up `/sessions/:id/view` route
- Pass `disabled={true}` to ChatPanel and `readOnly={true}` to SlidePanel (existing props)

**Step 4d - Verify GREEN**: Read-only tests pass

### Phase 5: Share Link Tests

**Step 5a - RED: Write share link tests** (`frontend/tests/share-link.spec.ts`):
```typescript
test('copy share link button generates view URL', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);

  await page.click('[data-testid="copy-share-link"]');

  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard).toMatch(new RegExp(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view$`));
});

test('share link opens to view mode', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);

  await page.click('[data-testid="copy-share-link"]');
  const shareUrl = await page.evaluate(() => navigator.clipboard.readText());

  const newPage = await context.newPage();
  // Re-setup mocks on new page
  await mockSessionWithSlides(newPage, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(newPage);
  await newPage.goto(shareUrl);

  await expect(newPage).toHaveURL(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/view`);
  await expect(newPage.locator('[data-testid="chat-input"]')).toBeDisabled();
});

test('copy share link shows success toast', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await mockSessionWithSlides(page, TEST_SESSION_WITH_SLIDES_ID);
  await setupMocks(page);
  await page.goto(`/sessions/${TEST_SESSION_WITH_SLIDES_ID}/edit`);

  await page.click('[data-testid="copy-share-link"]');

  await expect(page.locator('[data-testid="toast"]')).toContainText('Share link copied');
});
```

**Step 5b - Verify RED**: Tests fail (no share link button)

**Step 5c - GREEN: Add share link button**:
- Add button to Generator header (in AppShell when showSessionActions=true)
- Implement copy to clipboard
- Show success toast

**Step 5d - Verify GREEN**: Share link tests pass

### Test Utilities

**IMPORTANT**: Existing tests use Playwright **route mocking** (not real API calls). New tests must follow this pattern. See `frontend/tests/slide-generator.spec.ts` and `frontend/tests/fixtures/mocks.ts` for examples.

**Create helper functions** (`frontend/tests/helpers/session-helpers.ts`):
```typescript
import type { Page } from '@playwright/test';

// Fixed session IDs for deterministic test URLs
export const TEST_SESSION_ID = 'test-session-00000000-0000-0000-0000-000000000001';
export const TEST_SESSION_WITH_SLIDES_ID = 'test-session-00000000-0000-0000-0000-000000000002';

/**
 * Set up route mocks for a specific session that has slides.
 * Call this BEFORE navigating to the session URL.
 */
export async function mockSessionWithSlides(page: Page, sessionId: string = TEST_SESSION_WITH_SLIDES_ID) {
  // Mock session detail endpoint
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        title: 'Test Session With Slides',
        has_slide_deck: true,
        profile_id: 1,
        profile_name: 'Sales Analytics',
        created_at: '2026-01-08T20:38:56.749592',
        last_activity: '2026-01-08T20:42:11.058737',
        message_count: 3,
      })
    });
  });

  // Mock slides endpoint
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/slides`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSlides)  // Import from fixtures/mocks
    });
  });

  // Mock messages endpoint (for Viewer chat history)
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/messages`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        messages: [
          { role: 'user', content: 'Create slides about cloud computing', created_at: '2026-01-08T20:39:00' },
          { role: 'assistant', content: 'I\'ll create slides about cloud computing benefits.', created_at: '2026-01-08T20:39:30' },
        ]
      })
    });
  });

  // Mock versions endpoint
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}/versions`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ versions: [], current_version: null })
    });
  });
}

/**
 * Mock a session that returns 404 (doesn't exist).
 */
export async function mockSessionNotFound(page: Page, sessionId: string = 'nonexistent-id') {
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}`, (route) => {
    route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Session not found"}' });
  });
}
```

**NOTE**: All tests must also call the existing `setupMocks(page)` from `fixtures/mocks.ts` for profile/style/prompt endpoints that load on every page.

### Integration with Existing Tests

**Existing tests WILL BREAK** and must be updated. Key changes:

1. **`goToGenerator()` helper** (slide-generator.spec.ts line 90-95) — Currently clicks "Generator" button from `/`. After routing, this navigates to `/sessions/{id}/edit`. The helper must be updated to either:
   - Mock a session and navigate directly: `await page.goto('/sessions/test-id/edit')`
   - Or navigate via UI and wait for URL change: `await expect(page).toHaveURL(/\/sessions\/.*\/edit/)`

2. **Navigation tests** — Existing tests click nav buttons and check content. Now they should also verify URL changes.

3. **`data-testid` attributes** — Must be added to components during implementation. The existing tests use `page.getByRole()` and CSS selectors. New routing tests should use `data-testid` where role-based selectors are insufficient.

4. **Use base test fixture** — Import `{ test, expect }` from `./fixtures/base-test` (not `@playwright/test`) to get console error filtering.

### CI/CD Integration

Tests run in existing GitHub Actions workflow (`.github/workflows/test.yml`):
- Playwright tests run against full app (Vite dev server on port 3000)
- Frontend tests trigger on changes to `frontend/**` or `config/**`
- All routing tests must pass before merge

## Implementation Plan

### Phase 1: Setup & Core Routing (Low Risk)

**Files to create**:
- `frontend/tests/routing.spec.ts`

**Files to modify**:
- `frontend/package.json` (add react-router-dom)
- `frontend/src/main.tsx` (add BrowserRouter)
- `frontend/src/App.tsx` (add Routes structure)

**Steps**:
1. Write routing tests (RED)
2. Verify tests fail correctly
3. Install `react-router-dom` (no `@types` package needed — v6 includes types)
4. Add `<BrowserRouter>` wrapper in main.tsx
5. Create basic `<Routes>` in App.tsx with placeholder components
6. Verify tests pass (GREEN)

**Definition of done**:
- All Phase 1 routing tests pass
- Can navigate to basic routes
- URLs update correctly

### Phase 2: Session Integration (Medium Risk)

**Files to create**:
- `frontend/tests/session-loading.spec.ts`
- `frontend/tests/helpers/session-helpers.ts`
- `frontend/src/components/Generator.tsx`
- `frontend/src/components/AppShell.tsx`

**Files to modify**:
- `frontend/src/contexts/SessionContext.tsx`
- `frontend/src/App.tsx` (wire up Generator route)

**Steps**:
1. Write session loading tests (RED)
2. Verify tests fail correctly
3. Create ToastContext (needed for error display in session loading)
4. Extract AppShell from AppLayout (header/nav, preserve `isGenerating` guard on nav buttons)
5. Extract Generator from AppLayout (main viewMode logic + ALL save point state — see "Critical Context" section above for full state list)
6. Update SessionContext: add `lastWorkingSessionId` (localStorage-backed), change `createNewSession` to return new ID
7. Wire Generator to load session from URL params using existing `switchSession()`
8. Add error handling for invalid sessions (redirect to `/help`, show toast)
9. Verify tests pass (GREEN)

**Definition of done**:
- All Phase 2 session loading tests pass
- Generator loads sessions from URL
- Error handling works for invalid sessions
- Save points, verification, and all existing Generator features still work

### Phase 3: Navigation (Medium Risk)

**Files to create**:
- `frontend/tests/navigation.spec.ts`
- `frontend/src/pages/ProfilesPage.tsx`
- `frontend/src/pages/SlideStylesPage.tsx`
- `frontend/src/pages/DeckPromptsPage.tsx`
- `frontend/src/pages/ImagesPage.tsx`
- `frontend/src/pages/HistoryPage.tsx`
- `frontend/src/pages/HelpPage.tsx`

**Files to modify**:
- `frontend/src/components/AppShell.tsx` (replace setViewMode with navigate)
- `frontend/src/contexts/SessionContext.tsx` (add lastWorkingSessionId tracking)
- `frontend/src/components/History/SessionHistory.tsx` (navigate to session URLs)

**Steps**:
1. Write navigation tests (RED)
2. Verify tests fail correctly
3. Create page components wrapping existing views
4. Replace `setViewMode()` with `useNavigate()`
5. Update active state checks to use `useLocation()`
6. Implement "Generator" nav button logic (last session or new)
7. Update History page to navigate to session URLs
8. Verify tests pass (GREEN)

**Definition of done**:
- All Phase 3 navigation tests pass
- Nav buttons use URLs
- Browser back button works
- Generator nav returns to last session

### Phase 4: Read-Only Viewer (Higher Risk)

**Files to create**:
- `frontend/tests/viewer-readonly.spec.ts`
- `frontend/src/components/Viewer.tsx`

**Files to modify**:
- `frontend/src/App.tsx` (wire up Viewer route)
- Various components (add `data-testid` attributes for test selectors)

**Note**: ChatPanel already has `disabled` prop and SlidePanel already has `readOnly` prop. No prop changes needed.

**Steps**:
1. Write read-only viewer tests (RED)
2. Verify tests fail correctly
3. Create Viewer component — similar to Generator but passes `disabled={true}` to ChatPanel and `readOnly={true}` to SlidePanel
4. Viewer must load session data + chat messages via API on mount (for displaying read-only chat history)
5. Hide session action buttons (New, Save As, Save Points) in AppShell when `showSessionActions={false}`
6. Wire up `/sessions/:id/view` route
7. Add `data-testid` attributes to components as needed for test selectors
8. Verify tests pass (GREEN)

**Definition of done**:
- All Phase 4 viewer tests pass
- View mode disables editing (via existing props)
- Chat history visible but input disabled
- Export still available

### Phase 5: Share Links (Low Risk)

**Files to create**:
- `frontend/tests/share-link.spec.ts`

**Files to modify**:
- `frontend/src/components/AppShell.tsx` (add share link button)

**Steps**:
1. Write share link tests (RED)
2. Verify tests fail correctly
3. Add "Copy Share Link" button to AppShell (when showSessionActions)
4. Implement clipboard copy functionality
5. Add success toast
6. Verify tests pass (GREEN)

**Definition of done**:
- All Phase 5 share link tests pass
- Button copies view URL to clipboard
- Success toast appears

### Phase 6: Toast System & Polish (Low Risk)

**NOTE**: Server configuration is already complete (catch-all SPA route exists in `src/api/main.py`). No backend changes needed.

**Files to create**:
- `frontend/src/contexts/ToastContext.tsx` (provider + component + hook)

**Files to modify**:
- `frontend/src/App.tsx` (add ToastProvider to provider tree)

**Steps**:
1. Create ToastContext with `useToast()` hook returning `showToast(message, type)`
2. Create Toast component (auto-dismiss, success/error variants, `data-testid="toast"`)
3. Wire into App.tsx provider tree
4. Replace any `alert()` calls with `showToast()` where appropriate
5. Test all error flows work with toast notifications
6. Verify browser refresh preserves URLs on all routes

### Phase 7: Migration & Cleanup (Low Risk)

**Files to modify**:
- `frontend/src/main.tsx` or `SessionContext.tsx` (add migration logic)
- `frontend/src/components/Layout/AppLayout.tsx` (can be deleted after full migration)

**Steps**:
1. Add migration logic for existing sessions in localStorage
2. Test migration with existing user sessions
3. Remove obsolete localStorage keys after migration
4. Remove old AppLayout component (replaced by new structure)
5. Update documentation

**Definition of done**:
- Existing sessions migrate smoothly
- Old state cleaned up
- No breaking changes for users
- Documentation updated

## Rollout Plan

### Pre-Deployment Checklist
- [ ] All TDD phases complete (tests pass)
- [ ] Server configuration updated
- [ ] Migration logic tested
- [ ] Documentation updated
- [ ] Smoke tests pass in staging

### Deployment Steps
1. Deploy backend first (no changes, but good practice)
2. Deploy frontend with routing changes
3. Monitor errors for 404s, broken navigation
4. Smoke test key flows:
   - Create new session → URL updates
   - Share link → view mode works
   - Browser back button → navigation works
   - Migration → existing sessions load correctly

### Rollback Plan
If critical issues found:
- Revert to previous frontend build
- No data loss (backend unchanged)
- Sessions created with new version still accessible with old frontend
- Communicate to users about temporary routing issues

### Success Metrics (Post-Deployment)
- No increase in 404 errors
- Share links successfully created and accessed
- Browser navigation (back/forward) works without errors
- Session loading times remain consistent
- No user-reported navigation issues

## Future Enhancements

### Access Control Lists (ACLs)
- Add user authentication
- Implement permission system (view, edit, admin)
- Add permission checks in Generator/Viewer
- Add `/api/sessions/:id/permissions` endpoint
- Update share link UI to show permission level

### URL State Preservation
- Query params for filters (e.g., `/history?profile=xyz`)
- Slide-specific deep links (e.g., `/sessions/:id/view?slide=3`)
- Search state in history page

### Advanced Sharing
- Generate short URLs for sharing
- Expiring share links
- Password-protected view links
- Share with specific users/teams

### Analytics
- Track share link usage
- Monitor most-viewed presentations
- Understand navigation patterns

## Dependencies

### NPM Packages
```json
{
  "dependencies": {
    "react-router-dom": "^6.22.0"
  }
}
```

**Note**: `@types/react-router-dom` is NOT needed — React Router v6 ships its own TypeScript types.

### Install Command
```bash
cd frontend
npm install react-router-dom
```

## Files Summary

### New Files
- `frontend/src/components/AppShell.tsx` - Shared header/nav wrapper
- `frontend/src/components/Generator.tsx` - Main editing view (absorbs AppLayout's "main" viewMode)
- `frontend/src/components/Viewer.tsx` - Read-only view
- `frontend/src/contexts/ToastContext.tsx` - Toast notification system (provider + hook + component)
- `frontend/src/pages/ProfilesPage.tsx` - Profiles route wrapper
- `frontend/src/pages/SlideStylesPage.tsx` - Slide styles route wrapper
- `frontend/src/pages/DeckPromptsPage.tsx` - Deck prompts route wrapper
- `frontend/src/pages/ImagesPage.tsx` - Images route wrapper
- `frontend/src/pages/HistoryPage.tsx` - History route wrapper
- `frontend/src/pages/HelpPage.tsx` - Help route wrapper
- `frontend/tests/routing.spec.ts` - Core routing E2E tests
- `frontend/tests/session-loading.spec.ts` - Session URL tests
- `frontend/tests/navigation.spec.ts` - Navigation behavior tests
- `frontend/tests/viewer-readonly.spec.ts` - Read-only mode tests
- `frontend/tests/share-link.spec.ts` - Share functionality tests
- `frontend/tests/helpers/session-helpers.ts` - Test utilities (mock setup helpers)

### Modified Files
- `frontend/package.json` - Add react-router-dom
- `frontend/src/main.tsx` - Add BrowserRouter wrapper
- `frontend/src/App.tsx` - Replace AppLayout with Routes, add ToastProvider
- `frontend/src/contexts/SessionContext.tsx` - Add lastWorkingSessionId, change createNewSession to return ID
- `frontend/src/components/ChatPanel/ChatPanel.tsx` - Add data-testid attributes (disabled prop already exists)
- `frontend/src/components/ChatPanel/ChatInput.tsx` - Add data-testid attributes (disabled prop already exists)
- `frontend/src/components/SlidePanel/SlidePanel.tsx` - Add data-testid attributes (readOnly prop already exists)
- `frontend/src/components/History/SessionHistory.tsx` - Navigate to session URLs instead of calling onSessionSelect
- `frontend/tests/slide-generator.spec.ts` - Update goToGenerator() and navigation tests for URL routing
- `frontend/tests/fixtures/mocks.ts` - Add session detail mock data

### Removed Files (after migration complete)
- `frontend/src/components/Layout/AppLayout.tsx` - Replaced by AppShell + Generator + Viewer + page components

## Questions & Decisions

### Resolved
- **Q**: Should share links require authentication?
  **A**: No for MVP, public links. ACLs come later.

- **Q**: What URL for main generator view?
  **A**: `/sessions/:id/edit` (session-specific, not stateless root)

- **Q**: How to handle config page URLs?
  **A**: Standalone routes (`/profiles`, not `/settings/profiles`)

- **Q**: Browser back button behavior?
  **A**: Standard navigation (Option A), SessionContext tracks last session

- **Q**: Root URL behavior?
  **A**: Land on `/help` (matches current behavior)

### Resolved During Review
- **Server config**: Already implemented — FastAPI catch-all in `src/api/main.py` lines 189-201. No changes needed.
- **ChatPanel prop**: Uses `disabled` (not `readOnly`). Already exists.
- **SlidePanel prop**: Uses `readOnly`. Already exists.
- **Types package**: `@types/react-router-dom` not needed — v6 ships its own types.

### Open (To Be Resolved During Implementation)
- **Loading indicators**: Design for session load states (spinner vs skeleton)
- **Error messages**: Exact wording for toasts/banners
- **`data-testid` naming**: Convention for new attributes (suggest: `data-testid="chat-panel"`, `data-testid="slide-panel"`, `data-testid="chat-input"`, etc.)
- **Empty session view**: What to show at `/sessions/:id/view` when session has no slides (empty state? redirect?)
- **Profile change on config pages**: When user changes profile on `/profiles`, what happens to lastWorkingSessionId? (suggest: create new session, update lastWorkingSessionId)

## References

- React Router v6 docs: https://reactrouter.com/
- Current implementation: `frontend/src/components/Layout/AppLayout.tsx`
- Session management: `src/api/services/session_manager.py`
- Existing tests: `frontend/tests/*.spec.ts`

---

**Ready for implementation**: Follow TDD phases, write tests first, watch them fail, write minimal code to pass.
