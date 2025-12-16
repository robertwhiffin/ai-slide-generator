# Presentation Mode & Export

This document explains how the presentation mode feature works, including the custom fullscreen viewer and the standalone HTML export. Use it alongside `frontend-overview.md` for broader UI context.

---

## Feature Summary

Presentation mode displays slides in a fullscreen, keyboard-navigable viewer that shows one slide at a time. Users can also download a self-contained HTML file containing all slides for offline viewing or printing.

| Capability | Entry Point | Output |
| --- | --- | --- |
| Present fullscreen | "Present" button in SlidePanel header | Fullscreen overlay with single-slide iframe |
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

The presentation mode generates HTML for a single slide at a time. Each slide is wrapped in a container that maintains the 16:9 aspect ratio (1280×720px):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- external_scripts (Chart.js, etc.) -->
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    html, body {
      width: 100%;
      height: 100%;
      overflow: auto;
      background: #ffffff;
    }
    body {
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 0;
      margin: 0;
    }
    .slide-container {
      width: 1280px;
      height: 720px;
      position: relative;
      background: #ffffff;
      overflow: hidden;
      margin: 0;
    }
    .slide-container > * {
      width: 100%;
      height: 100%;
    }
    canvas {
      max-width: 100%;
      height: auto;
    }
    /* slideDeck.css */
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

### 4. Fullscreen Management

`PresentationMode` uses the Fullscreen API:
- On mount: `document.documentElement.requestFullscreen()` (with graceful fallback if denied)
- On fullscreen enter: Recalculates scale factor to account for viewport size changes
- On exit: Listens to `fullscreenchange` event; when `!document.fullscreenElement`, calls `onExit()`
- Cleanup: Exits fullscreen if component unmounts while still active

The component renders via React portal to `document.body`, creating a fullscreen overlay with black background. The scale factor is recalculated when entering fullscreen to ensure proper sizing in the new viewport.

### 5. Keyboard Navigation

Navigation is handled by React event listeners attached to `window` and `document` in capture phase:

```tsx
const handleKeyDown = (e: KeyboardEvent) => {
  // Skip if typing in input/textarea
  const target = e.target as HTMLElement;
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
    return;
  }

  switch (e.key) {
    case 'ArrowRight':
    case 'ArrowDown':
    case ' ': // Spacebar
      setCurrentSlideIndex((prev) => Math.min(prev + 1, slideDeck.slides.length - 1));
      break;
    case 'ArrowLeft':
    case 'ArrowUp':
      setCurrentSlideIndex((prev) => Math.max(prev - 1, 0));
      break;
    case 'Home':
      setCurrentSlideIndex(0);
      break;
    case 'End':
      setCurrentSlideIndex(slideDeck.slides.length - 1);
      break;
    case 'Escape':
      onExit();
      break;
  }
};
```

The container div has `tabIndex={-1}` and receives focus to capture keyboard events. The iframe does not receive focus; navigation is handled at the parent level.

---

## Component Responsibilities

| Path | Responsibility |
| --- | --- |
| `frontend/src/components/PresentationMode/PresentationMode.tsx` | Renders fullscreen portal with single-slide iframe, calculates and applies responsive scaling, manages fullscreen lifecycle, handles keyboard navigation, updates iframe content on slide change |
| `frontend/src/components/PresentationMode/index.ts` | Barrel export |
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Hosts Present/Export buttons, generates download HTML (all slides), toggles presentation state |

---

## Data Flow

### Present Flow

1. User clicks "Present" button in `SlidePanel`
2. `setIsPresentationMode(true)` renders `<PresentationMode>` via React portal to `document.body`
3. Component calculates initial scale factor based on viewport dimensions
4. Component requests fullscreen (with fallback if denied)
5. `useMemo` generates HTML for current slide (index 0 initially)
6. Iframe loads with `srcdoc={currentSlideHTML}` and applies scale transform
7. Container div receives focus to capture keyboard events
8. `waitForChartJs` polls then runs current slide's scripts
9. User navigates with arrow keys/Space; `currentSlideIndex` state updates
10. `useEffect` detects `currentSlideIndex` change, updates iframe `srcdoc` with new slide HTML
11. Scale recalculates automatically on window resize or orientation change
12. Escape key or fullscreen exit triggers `onExit()`, unmounting component

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
| Escape | Exit presentation mode |

Navigation hints are displayed in the top-right corner of the presentation overlay.

---

## Debug Mode

Raw HTML tabs are hidden by default to simplify the UI. Enable with:
- URL parameter: `?debug=true`
- LocalStorage: `localStorage.setItem('debug', 'true')`

When enabled, "Raw HTML (Rendered)" and "Raw HTML (Text)" tabs appear in `SlidePanel` for comparing agent output with parsed slides.

---

## Presentation Overlay UI

The presentation mode includes two overlays:

### Slide Counter (Bottom Center)
- Shows current slide number and total: `{currentSlideIndex + 1} / {slideDeck.slides.length}`
- Styled with semi-transparent black background, white text
- Positioned absolutely at bottom center

### Navigation Hints (Top Right)
- Displays: "← → Navigate | ESC Exit"
- Styled with semi-transparent black background, white text, reduced opacity
- Positioned absolutely at top right

Both overlays have `pointerEvents: 'none'` to allow clicks to pass through to the iframe.

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

- **Fullscreen denied:** Presentation still shows in overlay (graceful fallback)
- **Chart.js timeout:** After 50 attempts (5 seconds), logs error but continues
- **Script errors:** Logged to console but don't crash presentation
- **Keyboard events in inputs:** Ignored to allow typing in form fields within slides

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

- `currentSlideIndex`: Tracks which slide is currently displayed (0-based)
- `scale`: Calculated scale factor for responsive iframe sizing (maintains 16:9 aspect ratio)
- `iframeRef`: Reference to the iframe element for updating `srcdoc`
- `containerRef`: Reference to the container div for keyboard focus
- `wrapperRef`: Reference to the iframe wrapper div (for potential future use)

### HTML Generation

The `currentSlideHTML` is memoized with dependencies on `currentSlideIndex` and `slideDeck`. When either changes, new HTML is generated for the current slide, including:
- External scripts (Chart.js CDN links)
- Slide-specific CSS from `slideDeck.css`
- Current slide's HTML content
- Current slide's scripts (wrapped in `waitForChartJs`)

### Iframe Updates

When `currentSlideHTML` changes, a `useEffect` updates the iframe's `srcdoc` property, causing the iframe to reload with the new slide content. This ensures:
- Each slide's scripts execute independently
- Charts initialize correctly for each slide
- No state leakage between slides


