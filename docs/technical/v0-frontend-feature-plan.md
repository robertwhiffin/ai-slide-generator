# Plan: Support Main-Branch Features in v0 Frontend

This document outlines a phased plan to add support for the latest main-branch features into the v0 design system frontend (`feature/v0-frontend-refresh`). The backend already supports these features; the work is to wire them into the v0 UI (sidebar layout, PageHeader, and shared components).

---

## Feature inventory (main vs v0 frontend)

| Feature | Backend | v0 frontend today | Gap |
|--------|---------|--------------------|-----|
| **Per-user history** | ✅ `GET /api/sessions` filtered by `created_by` | ✅ Uses `api.listSessions()` | None – already per-user |
| **AI naming of sessions** | ✅ Session title from deck/slide title on save | ✅ `autoSaveSession(deck)` renames from deck title | None – already in place |
| **Share decks with links** | ✅ View route `/sessions/:id/view` (read-only) | ✅ Route exists; `viewOnly` passed to layout | **Add Share button** in header to copy view URL |
| **Versioning (Save Points)** | ✅ Versions API, create/revert/preview | ❌ No Save Points UI in v0 layout | **Add** dropdown, banner, revert modal, create-after-verify |
| **Save As** (custom session name) | ✅ `PATCH /api/sessions` rename | ❌ No “Save As” in v0 PageHeader | **Add** Save As action in header |
| **Improved PPT export** | ✅ Polling-based export API | ✅ SlidePanel has `exportPPTX()`; single Export button | **Optional:** export progress in header/subtitle |
| **Google Slides export** | ✅ OAuth + async export API | ❌ No Google Slides option in UI | **Add** Export dropdown (PPT / PDF / Google Slides) |
| **Image upload** | ✅ Upload API, paste in chat, library | ❌ v0 ChatInput is text-only; no Images page | **Add** image paste/upload in ChatInput + **Images** view in sidebar |
| **Feedback mechanism** | ✅ Survey, NPS, feedback API | ❌ No Feedback button or survey modal | **Add** FeedbackButton + SurveyModal + trigger on generation |
| **Improved slide edit handling** | ✅ Backend edit/replace flows | ✅ SlidePanel has verification, edit UI | **Optional:** ensure readOnly/viewOnly and version preview don’t allow edits |
| **URL routing for session** | ✅ `/sessions/:id/edit`, `/sessions/:id/view` | ✅ App.tsx has routes | **Wire** sessionId from URL into SessionContext on load |

---

## Phased implementation plan

### Phase 1 – Quick wins (routing, Share, Save As)

**Goal:** Align v0 with main for session URL and basic session actions.

1. **URL ↔ session sync**
   - In `AppLayout`, read `sessionId` from route (e.g. `useParams`) when path is `/sessions/:sessionId/edit` or `view`.
   - On load, if URL has `sessionId` and it differs from current session, call `switchSession(sessionId)` and load deck.
   - When creating or switching session, `navigate(`/sessions/${sessionId}/edit`)` so the URL always reflects the current session.

2. **Share button**
   - Add a “Share” (or “Copy link”) action to `PageHeader` (e.g. next to Export/Present).
   - On click: build `viewUrl = `${origin}/sessions/${sessionId}/view``, copy to clipboard, show toast (e.g. via `ToastContext`).
   - Disable when there is no `sessionId` or in view-only mode.

3. **Save As**
   - Add `onSave` to `PageHeader` (or a “Save As” button that opens a small dialog).
   - Implement “Save As” dialog: single text input for title, submit calls `renameSession(title)`, then refresh session list (e.g. `sessionsRefreshKey++`) and close dialog.
   - Pass `onSave` from `AppLayout` into `PageHeader`; only show when a session exists (and optionally when deck is loaded).

**Deliverables:** Share and Save As in header; opening a link or switching session updates URL and session state.

---

### Phase 2 – Versioning (Save Points)

**Goal:** Full versioning UX in v0 layout using existing Save Points components.

1. **State in AppLayout**
   - Add state: `versions`, `currentVersion`, `previewVersion`, `previewDeck`, `previewDescription`, `showRevertModal`, `revertTargetVersion`, `pendingSavePointDescription`.
   - Load versions when `sessionId` or `slideDeck` changes: `api.listVersions(sessionId)` and set `versions`, `currentVersion`.

2. **Header and main area**
   - Add `SavePointDropdown` to the header (e.g. next to Save As), with `versions`, `currentVersion`, `previewVersion`, `onPreview`, `onRevert`, `disabled={isGenerating}`.
   - When `previewVersion` is set, show `PreviewBanner` (version number, description, “Revert”, “Cancel”) and render `previewDeck` in the slide panel instead of live deck; panel and chat should be read-only or clearly in “preview” mode.
   - Add `RevertConfirmModal`; on confirm call `api.restoreVersion(sessionId, revertTargetVersion)`, set deck from response, clear preview state, reload versions.

3. **Create save point after verification**
   - When `ChatPanel` calls `onSlidesGenerated(deck, raw, actionDescription)`, pass `actionDescription` into `AppLayout`.
   - After verification completes (or when user clicks “Create save point” in panel), call `api.createSavePoint(sessionId, description)` and reload versions.
   - Optional: use `pendingSavePointDescription` so the “Create save point” flow can be triggered from the slide panel after verification (if that hook exists on main).

4. **SlidePanel / SelectionRibbon**
   - Pass `versionKey` (e.g. `previewVersion ? preview-v${previewVersion} : current-v${currentVersion}`) into `SelectionRibbon` and `SlidePanel` so that switching version forces a clean re-render.
   - Pass `readOnly={!!previewVersion}` (and/or `viewOnly`) so that in preview mode users cannot edit.

**Deliverables:** Save Points dropdown in header, preview banner, revert modal, and create-save-point after verification; version key and read-only behavior in panel.

---

### Phase 3 – Export (PPT, PDF, Google Slides)

**Goal:** Single Export entry point in header with PPT, PDF, and Google Slides options.

1. **Export dropdown in PageHeader**
   - Replace single “Export” button with a dropdown: “Export” → “Download PPTX”, “Download PDF”, “Export to Google Slides”.
   - “Download PPTX” / “Download PDF” call `slidePanelRef.current?.exportPPTX()` and `slidePanelRef.current?.exportPDF()` respectively (ensure SlidePanel exposes `exportPDF` on ref if not already).
   - “Export to Google Slides” starts async export (e.g. `api.exportToGoogleSlides(sessionId, slideDeck, onProgress)`), shows progress in header subtitle or a small toast, and on completion shows link (or “Open in Google Slides”) from API response.

2. **Progress and errors**
   - Use existing `onExportStatusChange` (or equivalent) so the header subtitle shows “Exporting…” / “Export to Google Slides…” during export.
   - Surface errors via toast or inline message.

3. **Google Slides auth**
   - If not already in v0: ensure admin/settings flow for Google OAuth is reachable (e.g. from Admin page or a “Connect Google Slides” in the export dropdown when not linked). Reuse `GoogleSlidesAuthForm` and backend OAuth routes.

**Deliverables:** Export dropdown with PPT, PDF, and Google Slides; progress and error handling; Google auth path for first-time setup.

---

### Phase 4 – Image upload and Images page

**Goal:** Paste/upload images in chat and a dedicated Images library page in v0.

1. **ChatInput**
   - Extend `ChatInput` to support optional image attachments (match main’s contract): `onSend(message, imageIds?: number[])`.
   - Add paste handling: on paste with image, upload via `api.uploadImage(file)`, add to local list of attachments, show thumbnails and “Save to library” checkbox.
   - Add explicit “Attach image” (or use existing `ImagePicker` from `ImageLibrary`) so users can pick from library or upload; pass selected image IDs with the message.
   - Keep v0 styling (e.g. `border-border`, `bg-card`) while adding the attachment UI.

2. **ChatPanel**
   - Ensure `ChatPanel` passes through `imageIds` when calling `onSend` and that the backend receives them (main already does).
   - If ChatPanel has `disabled`/`previewMessages`/other props from main, ensure they are still supported when adding image support.

3. **Images view in sidebar and layout**
   - Add `images` to `ViewMode` in `AppLayout` and `app-sidebar`.
   - Add a nav item “Images” (or “Image library”) in `app-sidebar` that sets `viewMode === 'images'`.
   - In `AppLayout`, when `viewMode === 'images'`, render the existing `ImageLibrary` component (full-page or in a scrollable area with `SimplePageHeader` “Image library”).
   - Ensure `ImageLibrary` and `ImagePicker` work with existing image API and v0 theme.

**Deliverables:** ChatInput supports paste + attach images and “Save to library”; Images page in sidebar; ImagePicker usable from chat and possibly from slide HTML editor.

---

### Phase 5 – Feedback and survey

**Goal:** Collect feedback and post-generation survey in v0.

1. **FeedbackButton**
   - Add the existing `FeedbackButton` (e.g. floating or in header/footer) to `AppLayout` so it’s visible on main and optionally other views.
   - Style it to match v0 (e.g. use `Button` from `@/ui/button` and existing Feedback popover content).

2. **SurveyModal**
   - Add `SurveyModal` to `AppLayout` (state: `showSurvey`, `closeSurvey`).
   - Integrate with `useSurveyTrigger`: on “generation complete” (e.g. when `onSlidesGenerated` fires and generation stops), call `onGenerationComplete()` so the survey can be shown after the first generation in a session (or per your product rules).
   - On “generation start”, call `onGenerationStart()` so the trigger can manage “show survey after this run”.

3. **Survey trigger hook**
   - Ensure `useSurveyTrigger` is used in `AppLayout` and that its `showSurvey`, `closeSurvey`, `onGenerationComplete`, `onGenerationStart` are wired to the modal and to `ChatPanel`/generation lifecycle (e.g. pass `onGenerationComplete` into the callback that handles `onSlidesGenerated`).

**Deliverables:** Feedback button visible in v0 layout; survey modal opens after generation when conditions are met; no duplicate modals.

---

### Phase 6 – Polish and behavior parity

**Goal:** View-only mode, export progress, and any remaining main behaviors.

1. **viewOnly / readOnly**
   - When route is `/sessions/:id/view`, `AppLayout` already receives `viewOnly={true}`. Ensure:
     - PageHeader hides or disables Share (or shows “Copy view link” only), Save As, Export, and Present (or only “Present” if view is allowed).
     - SlidePanel and ChatPanel are read-only (no edit, no send); optionally show a small “View only” badge.
   - If main has a “deleted profile” banner for sessions whose profile was deleted, add the same in v0 (state + banner in header).

2. **Export status in subtitle**
   - Keep passing `exportStatus` into `getSubtitle()` so the header shows “Exporting…” or “Export to Google Slides…” when an export is in progress.

3. **Session list refresh**
   - After Save As, Share (copy), or Create save point, increment `sessionsRefreshKey` so sidebar history and History page refresh (already partially there; ensure DeckHistory and SessionHistory both depend on it where appropriate).

4. **Help and docs**
   - Update Help content to mention Share link, Save As, Save Points, Export (including Google Slides), Image library, and Feedback so v0 users see the same guidance as main.

**Deliverables:** View-only behavior correct; export status visible; session list refreshes; help docs updated.

---

## Suggested order of work

1. **Phase 1** – Routing + Share + Save As (small, high value).
2. **Phase 2** – Versioning (Save Points) (high value, more state).
3. **Phase 3** – Export dropdown + Google Slides (medium complexity, depends on SlidePanel ref and API).
4. **Phase 4** – Image upload + Images page (ChatInput and new view).
5. **Phase 5** – Feedback + Survey (isolated UI + hook).
6. **Phase 6** – Polish and parity.

---

## Files to touch (by phase)

- **Phase 1:** `App.tsx`, `AppLayout.tsx`, `page-header.tsx`, `SessionContext.tsx` (if URL-driven session init), new small `SaveAsDialog` or reuse from main.
- **Phase 2:** `AppLayout.tsx`, `page-header.tsx`, `SlidePanel.tsx`, `SelectionRibbon.tsx`, `ChatPanel.tsx` (onSlidesGenerated callback); reuse `SavePointDropdown`, `PreviewBanner`, `RevertConfirmModal`.
- **Phase 3:** `page-header.tsx`, `SlidePanel.tsx` (ref API for exportPDF if needed), `api.ts` (Google Slides export); optional `GoogleSlidesAuthForm` entry from settings/admin.
- **Phase 4:** `ChatInput.tsx`, `ChatPanel.tsx`, `AppLayout.tsx`, `app-sidebar.tsx`, `ImageLibrary.tsx`, `ImagePicker.tsx`.
- **Phase 5:** `AppLayout.tsx`, `FeedbackButton.tsx`, `SurveyModal.tsx`, `useSurveyTrigger.ts`.
- **Phase 6:** `AppLayout.tsx`, `page-header.tsx`, `SlidePanel.tsx`, `HelpPage.tsx`.

---

## Reference: main-branch layout (for comparison)

On main, the header includes: Save Points dropdown, Save As button, New button, Share button (when URL has sessionId), and nav items (New Session, My Sessions, Profiles, Deck Prompts, Slide Styles, Images, Help). The v0 layout uses a sidebar for nav and history; the plan above keeps the v0 structure and adds the same *actions* (Save As, Share, Export dropdown, Save Points, Feedback) and views (Images) so that feature parity is achieved without replacing the v0 sidebar with the main top nav.
