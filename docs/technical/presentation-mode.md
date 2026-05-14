# Presentation Mode & Export

This document explains how the presentation mode feature works, including the custom fullscreen viewer and the standalone HTML export. Use it alongside `frontend-overview.md` for broader UI context.

---

## Feature Summary

Presentation mode displays slides in a keyboard-navigable viewer that shows one slide at a time. By default it opens "full window" — a fixed-position overlay covering `100vw × 100vh` — and can be promoted to browser fullscreen on demand (F or toolbar button), matching Google Slides' Slideshow / Cmd+Shift+Enter flow. Users can also download a self-contained HTML file containing all slides for offline viewing or printing.

| Capability | Entry Point | Output |
| --- | --- | --- |
| Present (full-window) | "Present" button in SlidePanel header | Fixed-position overlay with single-slide iframe; browser chrome still visible |
| Present (fullscreen) | F key or toolbar button inside the overlay | Browser fullscreen (`document.documentElement.requestFullscreen()`) |
| Start at current slide | "Present" button | Opens at whichever slide is most visible in the scroll viewport (or the selected one) |
| Download HTML | "Export" → "Save as HTML" in SlidePanel header | Standalone `.html` file with all slides |
| Debug mode | `?debug=true` or `localStorage.debug='true'` | Shows Raw HTML tabs |

---

## Stack & Entry Points

- **Components:** `frontend/src/components/PresentationMode/PresentationMode.tsx`, `frontend/src/components/SlidePanel/SlidePanel.tsx`
- **Dependencies:** Chart.js (from `SlideDeck.external_scripts`), React portals for fullscreen overlay
- **Trigger:** State toggle `isPresentationMode` in `SlidePanel`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ SlidePanel                                                   │
│ ┌──────────────┐ ┌──────────────┐                           │
│ │ Export btn   │ │ Present btn  │ ← triggers isPresentationMode │
│ └──────────────┘ └──────────────┘                           │
│         │                │                                   │
│         ▼                ▼                                   │
│   handleSaveAsHTML()  setIsPresentationMode(true)          │
│         │                │                                   │
│         │                ▼                                   │
│         │        ┌─────────────────────┐                    │
│         │        │ PresentationMode    │ ← portal to body   │
│         │        │ (fullscreen iframe) │                    │
│         │        │ - Single slide      │                    │
│         │        │ - Keyboard nav      │                    │
│         │        │ - Updates on change │                    │
│         │        └─────────────────────┘                    │
│         ▼                                                    │
│   Blob download                                              │
│   (all slides in one HTML)                                  │
└─────────────────────────────────────────────────────────────┘
```

The presentation mode shows one slide at a time in an iframe, updating the iframe's `srcdoc` when navigating. The download HTML includes all slides in a single document for offline viewing.

---

## Key Concepts

### 1. Presentation Mode HTML Structure

The presentation mode generates HTML for a single slide at a time. Each slide is wrapped in a `.slide-container` that maintains the 16:9 aspect ratio (1280×720px). **CSS ordering matters here** — the deck's own CSS (`slideDeck.css`) is injected before a final reset so deck styles can't squash the layout:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- external_scripts (Chart.js, etc.) -->
  <style>
    * { box-sizing: border-box; }
    html, body {
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #ffffff;
    }
    canvas { max-width: 100%; height: auto; }

    /* slideDeck.css is injected here */

    /* Reset AFTER deck CSS so per-deck rules can't override these */
    body {
      display: flex !important;
      justify-content: center !important;
      align-items: flex-start !important;
      padding: 0 !important;
      margin: 0 !important;
    }
    .slide-container {
      width: 1280px;
      height: 720px;
      flex-shrink: 0;
      flex-grow: 0;
      position: relative;
      background: #ffffff;
      overflow: hidden;
      margin: 0;
    }
    .slide-container > * {
      width: 100%;
      height: 100%;
      /* Zero any margin a deck CSS may add to its slide root — preview/gallery
         styles often set ".slide { margin: 40px auto }" which would push the
         slide inside the 720px clipping box and truncate the bottom. */
      margin: 0 !important;
    }
  </style>
</head>
<body>
  <div class="slide-container">
    <!-- slide.html for current slide -->
  </div>
  <script>
    waitForChartJs(() => { /* slide.scripts */ });
  </script>
</body>
</html>
```

Why each defensive rule exists:

- **`!important` body resets after the deck CSS** — Some slide styles set the body to a flex column with padding/gap (intended for a stacked-preview view). Without this reset, body padding could shrink the slide-container via flex-layout and clip the slide.
- **`flex-shrink: 0; flex-grow: 0;` on `.slide-container`** — Belt-and-braces: even if body padding sneaks through, the slide-container won't shrink below 720px.
- **`margin: 0 !important` on `.slide-container > *`** — Deck CSS commonly emits `.slide { margin: 40px auto }` for the gallery view. In present mode that 40px top margin pushes content past the 720px container and clips the bottom.

The iframe's `srcdoc` is updated whenever `currentSlideIndex` changes, causing a re-render of the slide content. The iframe itself is scaled using CSS `transform: scale()` to fit the viewport while maintaining the 16:9 aspect ratio without distortion.

### 2. Chart.js Polling

Charts require Chart.js to be loaded before initialization. The `waitForChartJs` helper polls until `typeof Chart !== 'undefined'`:

```javascript
function waitForChartJs(callback, maxAttempts = 50) {
  let attempts = 0;
  const check = () => {
    attempts++;
    if (typeof Chart !== 'undefined') {
      callback();
    } else if (attempts < maxAttempts) {
      setTimeout(check, 100);
    } else {
      console.error('[PresentationMode] Chart.js failed to load');
    }
  };
  check();
}
```

This ensures charts render correctly even when CDN load times vary. Each slide's scripts are executed individually when that slide is displayed.

### 3. Responsive Scaling

The presentation mode scales slides to fit any screen size while maintaining the 16:9 aspect ratio without distortion. This is achieved through dynamic scale calculation:

```tsx
const [scale, setScale] = useState(1);

useEffect(() => {
  const calculateScale = () => {
    const baseWidth = 1280;
    const baseHeight = 720;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    const scaleX = viewportWidth / baseWidth;
    const scaleY = viewportHeight / baseHeight;
    
    // Use the smaller scale to ensure content fits without distortion
    const newScale = Math.min(scaleX, scaleY);
    setScale(newScale);
  };

  calculateScale();
  window.addEventListener('resize', calculateScale);
  window.addEventListener('orientationchange', calculateScale);

  return () => {
    window.removeEventListener('resize', calculateScale);
    window.removeEventListener('orientationchange', calculateScale);
  };
}, []);
```

The iframe is then scaled using CSS transform:

```tsx
<iframe
  style={{
    width: '1280px',
    height: '720px',
    transform: `scale(${scale})`,
    transformOrigin: 'center center',
  }}
/>
```

This approach:
- Maintains the 16:9 aspect ratio at all screen sizes
- Prevents distortion by using the smaller of width/height scale ratios
- Automatically adjusts on window resize and orientation changes
- Recalculates scale when entering fullscreen mode

### 4. Full-Window Default + Opt-in Fullscreen

`PresentationMode` defaults to **full window**: a React portal mounted on `document.body` with `position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; zIndex: 9999`. The browser chrome stays visible (so the user can still see their tabs / URL bar) — this is the same UX as Google Slides' "Slideshow" view.

Browser fullscreen is **opt-in** and toggles in either direction via:
- The `F` key, or
- The fullscreen toggle button in the top-right toolbar

```tsx
const toggleFullscreen = () => {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  } else {
    document.documentElement.requestFullscreen().catch(() => {});
  }
};
```

A `fullscreenchange` listener mirrors the browser's actual fullscreen state into local `isFullscreen` state and recalculates the scale factor (viewport dimensions change when fullscreen toggles). The listener does **not** call `onExit` — exiting fullscreen drops the user back to full-window, not all the way out of presentation mode. To fully exit, the user presses Esc a second time.

The resulting Esc behavior is naturally two-stage, like Keynote/PowerPoint:

| Mode | Esc behavior |
| --- | --- |
| Fullscreen | Browser intercepts Esc and exits fullscreen → drops to full-window |
| Full-window | Component's keydown handler fires `onExit()` → exits presentation entirely |

On unmount the component releases any held fullscreen lock with `document.exitFullscreen()`.

### 5. Keyboard Navigation

Navigation is handled by a single keydown function stored in a ref so it can be attached to multiple targets without re-defining:

| Key | Action |
| --- | --- |
| → / ↓ / Space | Next slide |
| ← / ↑ | Previous slide |
| Home / End | Jump to first / last slide |
| F | Toggle browser fullscreen |
| Esc | Exit (two-stage — see Full-Window section above) |

The handler is attached to **three** targets:

1. `window` and `document` of the parent page (capture phase) — catches keys when focus is on the body or any non-iframe element.
2. The iframe's `contentDocument` — re-attached on every iframe `srcdoc` load. Without this, if focus lands inside the iframe (which happens after tab switch back, after re-entering fullscreen, or after clicking on slide content), keydown events fire inside the iframe and don't bubble to the parent window.

A `visibilitychange` listener also refocuses the container when the tab becomes visible again, so the parent-level listener has a chance to receive keys cleanly.

The handler short-circuits if the event target is an `INPUT`, `TEXTAREA`, or `contenteditable` element, so users can still type in form fields embedded in slides.

### 6. Deck Snapshot (Freeze Prevention)

`PresentationMode` snapshots the `slideDeck` prop into a ref on mount and reads from the snapshot for everything thereafter:

```tsx
const deckSnapshotRef = useRef(slideDeck);
const deck = deckSnapshotRef.current;
```

This is **not just an optimization** — it's a correctness fix. `ChatPanel` polls `/api/sessions/<id>/mentions` every 3 seconds, which re-renders `SlidePanel` and passes a new `slideDeck` reference to `<PresentationMode>` on every poll. Before snapshotting, the component's `useMemo([currentSlideIndex, slideDeck])` recomputed the iframe `srcdoc` every 3s, causing the iframe to reload mid-keypress and stalling navigation. Symptom: the presentation "froze" after a few seconds of inactivity.

Snapshotting also matches the user expectation set by Google Slides — edits made in the chat panel while presenting **do not** retroactively update the open presentation. To see edits, the user re-opens Present.

### 7. Start at Current Slide

`SlidePanel` resolves a "current slide" index at the moment the Present button is clicked, and passes it to `<PresentationMode>` as `startIndex`:

```tsx
const openPresentationFromActive = useCallback(() => {
  const total = slideDeck?.slides.length ?? 0;
  let idx = 0;

  if (selectedIndices.length > 0) {
    // Explicit selection wins
    idx = selectedIndices[0];
  } else {
    // Pick the slide spanning a virtual trigger line ~25% from the top
    const triggerY = window.innerHeight * 0.25;
    for (const [tileIndex, el] of slideRefs.current) {
      const r = el.getBoundingClientRect();
      if (r.top <= triggerY && r.bottom > triggerY) {
        idx = tileIndex;
        break;
      }
    }
  }

  setPresentationStartIndex(Math.max(0, Math.min(idx, Math.max(0, total - 1))));
  setIsPresentationMode(true);
}, [selectedIndices, slideDeck]);
```

Two rules:

- **Explicit selection wins.** If the user has clicked/selected a slide, present from there.
- **Otherwise, trigger line at 25% from top.** The slide whose bounding box covers the line is "current". This pattern matches docs-site TOC highlighting and is stable as you scroll — the trigger only advances when one tile's bottom edge crosses above the line, so adjacent tiles don't oscillate when they're equally visible.

Computed on click (not via a live observer) — cheaper, deterministic, and avoids stale state during fast scrolling.

---

## Component Responsibilities

| Path | Responsibility |
| --- | --- |
| `frontend/src/components/PresentationMode/PresentationMode.tsx` | Renders the full-window portal with single-slide iframe; snapshots the deck to immunize against parent re-renders; manages opt-in browser fullscreen; handles keyboard navigation across parent + iframe documents; auto-hides chrome in fullscreen |
| `frontend/src/components/PresentationMode/index.ts` | Barrel export |
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Hosts Present/Export buttons, resolves "current slide" on Present click (selection wins → else trigger-line at 25% from top), generates download HTML (all slides), toggles presentation state |

---

## Data Flow

### Present Flow

1. User clicks "Present" button in `SlidePanel`
2. `openPresentationFromActive` resolves `startIndex` (selected slide, else slide at the 25%-from-top trigger line)
3. `setIsPresentationMode(true)` renders `<PresentationMode>` via React portal to `document.body`
4. Component snapshots the deck into `deckSnapshotRef` so the iframe is immune to upstream re-renders (e.g. ChatPanel's 3s polling)
5. Component calculates initial scale factor based on viewport dimensions
6. `useMemo` generates HTML for the starting slide
7. Iframe loads with `srcdoc={currentSlideHTML}` and applies scale transform from `transformOrigin: center center`
8. Container div receives focus; keydown handler is also attached to the iframe's `contentDocument` so navigation works regardless of which document holds focus
9. `waitForChartJs` polls then runs current slide's scripts
10. Keyboard-shortcut hint is visible for ~3s, then fades out
11. User navigates with arrow keys / Space; `currentSlideIndex` updates
12. `useEffect` updates iframe `srcdoc` on slide change; the keydown listener is re-attached to the new `contentDocument` on each load
13. Scale recalculates automatically on window resize, orientation change, and fullscreen toggle
14. (Optional) F key or toolbar button toggles browser fullscreen; toolbar/hint/counter all hide while fullscreen is active
15. Esc unwinds fullscreen first (browser-handled); a second Esc exits the presentation entirely via the component's keydown handler

### Download Flow

1. User clicks "Export" → "Save as HTML" button
2. `handleSaveAsHTML()` generates HTML string containing all slides
3. Each slide wrapped in `.slide-wrapper` with `.slide-container`
4. All slides' scripts wrapped in IIFEs, executed after Chart.js loads
5. Creates Blob with `text/html` MIME type
6. Triggers download via temporary anchor element
7. Filename derived from `slideDeck.title` (sanitized, lowercase, hyphens)

---

## Slide Container Configuration

| Property | Value | Purpose |
| --- | --- | --- |
| `width` | 1280px | Match slide design dimensions |
| `height` | 720px | Match slide design dimensions (16:9 aspect ratio) |
| `overflow` | hidden | Prevent scrolling (scaling handles viewport fit) |
| `background` | #ffffff | White background for slides |

The iframe wrapper uses CSS `transform: scale()` to scale the 1280×720px iframe proportionally to fit the viewport. The scale factor is calculated dynamically based on viewport dimensions, ensuring the content fits without distortion while maintaining the 16:9 aspect ratio.

---

## Keyboard Shortcuts

| Key | Action |
| --- | --- |
| ← / ↑ | Previous slide |
| → / ↓ | Next slide |
| Space | Next slide |
| Home | Jump to first slide |
| End | Jump to last slide |
| F | Toggle browser fullscreen |
| Escape | Exit fullscreen (if active) → exit presentation (if already full-window) |

A navigation hint (`← → Navigate · F Fullscreen · Esc Exit`) appears in the top-left for the first ~3 seconds after open, then fades out so it stops covering slide content. In fullscreen the hint stays hidden.

---

## Debug Mode

Raw HTML tabs are hidden by default to simplify the UI. Enable with:
- URL parameter: `?debug=true`
- LocalStorage: `localStorage.setItem('debug', 'true')`

When enabled, "Raw HTML (Rendered)" and "Raw HTML (Text)" tabs appear in `SlidePanel` for comparing agent output with parsed slides.

---

## Presentation Overlay UI

The overlay has three pieces of chrome, all of which **auto-hide in fullscreen** so the slides own the screen (the user is expected to know F/Esc/arrows once they've committed to fullscreen). In full-window mode, the toolbar and counter stay visible; only the hint auto-hides after 3 seconds.

### Slide Counter (Bottom Center)
- Shows current slide number and total: `{currentSlideIndex + 1} / {slideCount}` (`slideCount` comes from the deck snapshot, not the live prop)
- Semi-transparent black background, white text
- `pointerEvents: 'none'` so clicks pass through to the iframe

### Toolbar (Top Right)
- Two interactive buttons rendered with inline SVG icons (Unicode glyphs like `⤢ / ⤡ / ✕` render inconsistently across fonts/OSes):
  - Fullscreen toggle (`F` shortcut equivalent) — icon swaps between "enter" and "exit" arrows
  - Close (`Esc` shortcut equivalent)
- `pointerEvents` flips to `none` while hidden so users can't accidentally click an invisible button

### Navigation Hint (Top Left)
- `← → Navigate · F Fullscreen · Esc Exit`
- Visible only for the first ~3 seconds after open, then fades out (opacity transition)
- `pointerEvents: 'none'`

---

## Download HTML Structure

The "Save as HTML" export generates a different structure than presentation mode:

- **All slides in one document**: Each slide wrapped in `.slide-wrapper` with `.slide-container`
- **Vertical layout**: Slides stacked vertically with `gap: 40px` for scrolling/printing
- **Page breaks**: `page-break-after: always` on each slide wrapper for printing
- **Script execution**: Each slide's scripts wrapped in IIFEs, executed after Chart.js loads
- **Deck-level scripts**: Executed once after all slides are initialized

This format is optimized for:
- Offline viewing (single file, no network dependencies)
- Printing (page breaks between slides)
- Sharing (self-contained HTML file)

---

## Operational Notes

### Console Debugging

When presenting, the following logs appear in the iframe's console (for each slide):
```
[PresentationMode] Initializing charts for slide N...
[PresentationMode] Charts initialized successfully
```

If Chart.js fails to load:
```
[PresentationMode] Chart.js failed to load
```

If chart initialization fails:
```
[PresentationMode] Chart initialization error: [error details]
```

### Error Handling

- **Fullscreen denied:** No effect on default flow (we never auto-request fullscreen). If a user invokes F/the toolbar button and the browser denies the request, the promise rejection is swallowed and the presentation stays in full-window.
- **Chart.js timeout:** After 50 attempts (5 seconds), logs error but continues
- **Script errors:** Logged to console but don't crash presentation
- **Keyboard events in inputs:** Ignored to allow typing in form fields within slides
- **Focus lost to iframe:** Mitigated by attaching the keydown listener to the iframe's `contentDocument` on every load, plus a `visibilitychange` listener that refocuses the container when the tab regains visibility

### Iframe Sandbox

The iframe uses `sandbox="allow-scripts allow-same-origin"` to:
- Allow JavaScript execution (for Chart.js and slide scripts)
- Allow same-origin access (for proper rendering)
- Maintain security by restricting other capabilities

---

## Extension Guidance

1. **Add speaker notes:** Display notes in a separate overlay or side panel, toggle with a key
2. **Slide transitions:** Add CSS transitions when `currentSlideIndex` changes (fade, slide, etc.)
3. **Touch gestures:** Add swipe detection for mobile/tablet navigation
4. **Timer/clock:** Add presentation timer overlay
5. **Remote control:** WebSocket integration to sync presenter/audience views
6. **Slide thumbnails:** Add thumbnail strip for quick navigation
7. **Notes panel:** Side panel showing speaker notes for current slide
8. **Export enhancements:** Add options for PDF export, reveal.js format, or PowerPoint

---

## Cross-References

- `docs/technical/frontend-overview.md` — UI architecture, SelectionContext, API client
- `docs/technical/slide-parser-and-script-management.md` — How `SlideDeck` stores CSS, scripts, and slides
- `docs/technical/backend-overview.md` — API endpoints that provide slide data
- `docs/technical/export-features.md` — PDF and PowerPoint export functionality

---

## Key Files

| Concern | File |
| --- | --- |
| Presentation component | `frontend/src/components/PresentationMode/PresentationMode.tsx` |
| Presentation export | `frontend/src/components/PresentationMode/index.ts` |
| SlidePanel integration | `frontend/src/components/SlidePanel/SlidePanel.tsx` |
| SlideDeck type | `frontend/src/types/slide.ts` |
| Backend slide model | `src/domain/slide_deck.py` |

---

## Implementation Details

### State Management

State (`useState`):
- `currentSlideIndex` — Which slide is currently displayed (0-based; initialized from the `startIndex` prop)
- `scale` — Calculated scale factor for responsive iframe sizing
- `isFullscreen` — Mirrors `!!document.fullscreenElement`; drives chrome visibility
- `hintVisible` — `true` for the first 3s, then `false`. Combined with `controlsVisible` to drive hint opacity

Derived: `controlsVisible = !isFullscreen` — single switch for toolbar/counter/hint visibility.

Refs:
- `iframeRef` — Iframe element, used to push `srcdoc` updates without React reconciliation
- `containerRef` — The portal container, used for focus management
- `wrapperRef` — Iframe wrapper (legacy; available for future use)
- `onExitRef` — Stabilizes the `onExit` callback so it can be read from event handlers without re-running effects on parent re-renders
- `toggleFullscreenRef` — Same pattern for the fullscreen toggle (invoked from the keydown handler)
- `handleKeyDownRef` — Single source of truth for the keydown logic; attached to parent window/document AND to the iframe's `contentDocument` on each load
- `deckSnapshotRef` — Captures the `slideDeck` prop on mount; the iframe HTML reads from this snapshot, not the live prop (see "Deck Snapshot" above)

### HTML Generation

`currentSlideHTML` is memoized with **dependencies on `[currentSlideIndex]` only** — the deck is read from `deckSnapshotRef.current`, not the live `slideDeck` prop, so parent re-renders (e.g. the 3s mentions poll) don't recompute the HTML or reload the iframe.

The memoized HTML includes:
- External scripts (Chart.js CDN links)
- Deck-level CSS (`deck.css`), followed by the `!important` reset
- Current slide's HTML content
- Current slide's scripts (wrapped in `waitForChartJs`)

### Iframe Updates

When `currentSlideHTML` changes, a `useEffect` updates the iframe's `srcdoc` property, causing the iframe to reload with the new slide content. The `handleIframeLoad` callback then:

1. Refocuses the container so keyboard nav keeps working
2. Re-attaches the keydown listener to the **new** `contentDocument` (the old one was destroyed by the srcdoc swap)

This ensures:
- Each slide's scripts execute independently
- Charts initialize correctly for each slide
- Navigation works regardless of which document currently holds focus
- No state leakage between slides


