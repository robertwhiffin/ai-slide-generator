# Presentation Mode & Export

This document explains how the presentation mode feature works, including the fullscreen reveal.js viewer and the standalone HTML export. Use it alongside `frontend-overview.md` for broader UI context.

---

## Feature Summary

Presentation mode transforms the parsed `SlideDeck` into a fullscreen, keyboard-navigable slideshow using [reveal.js](https://revealjs.com/). Users can also download a self-contained HTML file that works offline in any browser.

| Capability | Entry Point | Output |
| --- | --- | --- |
| Present fullscreen | "Present" button in SlidePanel header | Fullscreen overlay with reveal.js |
| Download HTML | "Download" button in SlidePanel header | Standalone `.html` file |
| Debug mode | `?debug=true` or `localStorage.debug='true'` | Shows Raw HTML tabs |

---

## Stack & Entry Points

- **Components:** `frontend/src/components/PresentationMode/PresentationMode.tsx`, `frontend/src/components/SlidePanel/SlidePanel.tsx`
- **Dependencies:** reveal.js v5 (loaded via CDN), Chart.js (from `SlideDeck.external_scripts`)
- **Trigger:** State toggle `isPresentationMode` in `SlidePanel`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ SlidePanel                                                   │
│ ┌──────────────┐ ┌──────────────┐                           │
│ │ Download btn │ │ Present btn  │ ← triggers isPresentationMode │
│ └──────────────┘ └──────────────┘                           │
│         │                │                                   │
│         ▼                ▼                                   │
│   handleDownload()   setIsPresentationMode(true)            │
│         │                │                                   │
│         │                ▼                                   │
│         │        ┌─────────────────────┐                    │
│         │        │ PresentationMode    │ ← portal to body   │
│         │        │ (fullscreen iframe) │                    │
│         │        └─────────────────────┘                    │
│         ▼                                                    │
│   Blob download                                              │
│   (standalone HTML)                                          │
└─────────────────────────────────────────────────────────────┘
```

Both paths generate identical HTML with reveal.js, Chart.js polling, and the deck's CSS/scripts embedded.

---

## Key Concepts

### 1. Generated HTML Structure

The presentation HTML wraps each slide in a reveal.js `<section>`:

```html
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/white.css">
  <!-- external_scripts (Chart.js, etc.) -->
  <style>/* slideDeck.css */</style>
</head>
<body>
  <div class="reveal-viewport">
    <div class="reveal">
      <div class="slides">
        <section><!-- slide[0].html --></section>
        <section><!-- slide[1].html --></section>
        ...
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
  <script>
    Reveal.initialize({ width: 1280, height: 720, ... });
    waitForChartJs(() => { /* slideDeck.scripts */ });
  </script>
</body>
</html>
```

### 2. Chart.js Polling

Charts require Chart.js to be loaded before initialization. The `waitForChartJs` helper polls until `typeof Chart !== 'undefined'`:

```javascript
function waitForChartJs(callback, maxAttempts = 50) {
  let attempts = 0;
  const check = () => {
    if (typeof Chart !== 'undefined') callback();
    else if (attempts++ < maxAttempts) setTimeout(check, 100);
  };
  check();
}
```

This ensures charts render correctly even when CDN load times vary.

### 3. Fullscreen Management

`PresentationMode` uses the Fullscreen API:
- On mount: `document.documentElement.requestFullscreen()`
- On exit: Listens to `fullscreenchange` event; when `!document.fullscreenElement`, calls `onExit()`
- Cleanup: Exits fullscreen if component unmounts while still active

### 4. Iframe Focus for Keyboard Navigation

The iframe must receive focus for reveal.js keyboard shortcuts to work:

```tsx
const handleIframeLoad = () => {
  iframeRef.current?.focus();
};
```

---

## Component Responsibilities

| Path | Responsibility |
| --- | --- |
| `frontend/src/components/PresentationMode/PresentationMode.tsx` | Renders fullscreen portal with reveal.js iframe, manages fullscreen lifecycle |
| `frontend/src/components/PresentationMode/index.ts` | Barrel export |
| `frontend/src/components/SlidePanel/SlidePanel.tsx` | Hosts Present/Download buttons, generates download HTML, toggles presentation state |

---

## Data Flow

### Present Flow

1. User clicks "Present" button
2. `setIsPresentationMode(true)` renders `<PresentationMode>` via React portal
3. Component requests fullscreen and generates HTML from `slideDeck`
4. Iframe loads, auto-focuses, reveal.js initializes
5. `waitForChartJs` polls then runs `slideDeck.scripts`
6. User navigates with arrow keys; Escape exits fullscreen
7. `fullscreenchange` event triggers `onExit()`, unmounting component

### Download Flow

1. User clicks "Download" button
2. `handleDownload()` generates identical HTML string
3. Creates Blob with `text/html` MIME type
4. Triggers download via temporary anchor element
5. Filename derived from `slideDeck.title` (sanitized)

---

## Reveal.js Configuration

| Option | Value | Purpose |
| --- | --- | --- |
| `width` | 1280 | Match slide design dimensions |
| `height` | 720 | Match slide design dimensions |
| `margin` | 0 | No padding around slides |
| `center` | true | Center slides in viewport |
| `controls` | true | Show navigation arrows |
| `progress` | true | Show progress bar |
| `slideNumber` | true | Display slide number |
| `transition` | 'slide' | Horizontal slide animation |
| `keyboard` | `{ 27: null }` | Disable reveal.js Escape handling (use fullscreen API instead) |
| `hash` | true (download) / false (present) | URL hash navigation for downloaded files |

---

## Keyboard Shortcuts (Reveal.js Defaults)

| Key | Action |
| --- | --- |
| ← / → | Previous / Next slide |
| ↑ / ↓ | Previous / Next vertical slide |
| Space | Next slide |
| Escape | Exit fullscreen |
| F | Toggle fullscreen (reveal.js) |
| O | Overview mode |
| S | Speaker notes (if present) |

---

## Debug Mode

Raw HTML tabs are hidden by default to simplify the UI. Enable with:
- URL parameter: `?debug=true`
- LocalStorage: `localStorage.setItem('debug', 'true')`

When enabled, "Raw HTML (Rendered)" and "Raw HTML (Text)" tabs appear for comparing agent output with parsed slides.

---

## CSS Overrides for Slides

The generated HTML includes overrides to make slides fill the reveal.js viewport:

```css
.reveal .slides section .slide {
  width: 100% !important;
  height: 100% !important;
  min-height: 100% !important;
  max-height: 100% !important;
}
```

This ensures the fixed 1280×720 slide content scales properly within reveal.js's responsive layout.

---

## Operational Notes

### Console Debugging

When presenting, the following logs appear in the iframe's console:
```
[PresentationMode] Reveal.js initialized
[PresentationMode] Initializing charts...
[PresentationMode] Charts initialized successfully
```

Parent window logs:
```
[PresentationMode] Generated HTML: <!DOCTYPE html>...
[PresentationMode] Slide count: N
[PresentationMode] External scripts: [...]
```

### Error Handling

- **Fullscreen denied:** Presentation still shows in overlay (graceful fallback)
- **Chart.js timeout:** After 50 attempts (5 seconds), gives up silently
- **Script errors:** Logged to console but don't crash presentation

---

## Extension Guidance

1. **Add speaker notes:** Embed notes in slide HTML, reveal.js will detect them
2. **Custom themes:** Replace `white.css` CDN link or inject theme CSS via `slideDeck.css`
3. **Export to PDF:** Reveal.js supports `?print-pdf` query param; extend download to offer PDF mode
4. **Vertical slides:** Nest `<section>` tags in slide HTML for vertical navigation
5. **Remote control:** Reveal.js multiplex plugin could sync presenter/audience views

---

## Cross-References

- `docs/technical/frontend-overview.md` — UI architecture, SelectionContext, API client
- `docs/technical/slide-parser-and-script-management.md` — How `SlideDeck` stores CSS, scripts, and slides
- `docs/technical/backend-overview.md` — API endpoints that provide slide data

---

## Key Files

| Concern | File |
| --- | --- |
| Presentation component | `frontend/src/components/PresentationMode/PresentationMode.tsx` |
| SlidePanel integration | `frontend/src/components/SlidePanel/SlidePanel.tsx` |
| SlideDeck type | `frontend/src/types/slide.ts` |
| Backend slide model | `src/domain/slide_deck.py` |

