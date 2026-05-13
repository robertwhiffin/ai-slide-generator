import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { SlideDeck } from '../../types/slide';

interface PresentationModeProps {
  slideDeck: SlideDeck;
  onExit: () => void;
  startIndex?: number;
}

export const PresentationMode: React.FC<PresentationModeProps> = ({
  slideDeck,
  onExit,
  startIndex = 0,
}) => {
  const [currentSlideIndex, setCurrentSlideIndex] = useState(startIndex);
  const [scale, setScale] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const onExitRef = useRef(onExit);
  onExitRef.current = onExit;

  // Snapshot deck on mount so periodic parent re-renders (e.g. ChatPanel's 3s
  // mentions polling) don't reload the iframe by changing the slideDeck prop
  // reference. Slides edited from chat are intentionally not reflected until
  // the next time presentation mode is opened — matches Google Slides behavior.
  const deckSnapshotRef = useRef(slideDeck);
  const deck = deckSnapshotRef.current;
  const slideCount = deck.slides.length;

  // Generate HTML for current slide (no reveal.js)
  const currentSlideHTML = useMemo(() => {
    const slide = deck.slides[currentSlideIndex];
    const slideScripts = slide.scripts || '';

    const externalScriptsHtml = deck.external_scripts
      .map((src) => `<script src="${src}"></script>`)
      .join('\n');

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${externalScriptsHtml}
  <style>
    * {
      box-sizing: border-box;
    }
    html, body {
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #ffffff;
    }
    /* Chart canvas scaling */
    canvas {
      max-width: 100%;
      height: auto;
    }
    ${deck.css}
    /* Reset body styles AFTER deck CSS so per-deck CSS can't squash the slide
       by adding body padding/flex centering (which would shrink the 720px
       slide-container via flex layout and clip content at the top). */
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
      /* Zero any margin a deck CSS may add to its slide root — margins push
         the slide inside the 720px clipping container and cause bottom-edge
         truncation (e.g. ".slide { margin: 40px auto }" preview-mode styles). */
      margin: 0 !important;
    }
  </style>
</head>
<body>
  <div class="slide-container">
    ${slide.html}
  </div>
  <script>
    // Wait for Chart.js to be available before running scripts
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

    function initializeCharts() {
      console.log('[PresentationMode] Initializing charts for slide ${currentSlideIndex + 1}...');
      try {
        ${slideScripts}
        console.log('[PresentationMode] Charts initialized successfully');
      } catch (err) {
        console.error('[PresentationMode] Chart initialization error:', err);
      }
    }

    // Initialize charts after DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        waitForChartJs(initializeCharts);
      });
    } else {
      waitForChartJs(initializeCharts);
    }
  </script>
</body>
</html>`;
    // deck is captured once via deckSnapshotRef; only the active slide changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSlideIndex]);

  // Calculate scale factor to fit viewport while maintaining aspect ratio
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

  // Update iframe content when slide changes
  useEffect(() => {
    if (iframeRef.current) {
      iframeRef.current.srcdoc = currentSlideHTML;
    }
  }, [currentSlideHTML]);

  // Single source of truth for keyboard handling, stored in a ref so it can be
  // attached to the iframe's contentDocument on every load (see handleIframeLoad)
  // without re-defining the handler. Without this, if focus lands inside the
  // iframe — which happens after a tab switch back, after entering fullscreen,
  // or after a click into slide content — keydown events fire in the iframe's
  // document and don't bubble up to the parent window, so navigation breaks.
  const handleKeyDownRef = useRef<(e: KeyboardEvent) => void>(() => {});
  handleKeyDownRef.current = (e: KeyboardEvent) => {
    const target = e.target as HTMLElement | null;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
      return;
    }
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
      case ' ': // Spacebar
        e.preventDefault();
        e.stopPropagation();
        setCurrentSlideIndex((prev) => Math.min(prev + 1, slideCount - 1));
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        e.stopPropagation();
        setCurrentSlideIndex((prev) => Math.max(prev - 1, 0));
        break;
      case 'Home':
        e.preventDefault();
        e.stopPropagation();
        setCurrentSlideIndex(0);
        break;
      case 'End':
        e.preventDefault();
        e.stopPropagation();
        setCurrentSlideIndex(slideCount - 1);
        break;
      case 'f':
      case 'F':
        e.preventDefault();
        e.stopPropagation();
        toggleFullscreenRef.current();
        break;
      case 'Escape':
        e.preventDefault();
        e.stopPropagation();
        onExitRef.current();
        break;
    }
  };

  // Re-grab focus when returning to the tab so the parent listener actually
  // sees keypresses. The iframe listener (attached in handleIframeLoad) covers
  // the case where focus is in the iframe itself.
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && containerRef.current) {
        containerRef.current.focus();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => handleKeyDownRef.current(e);
    window.addEventListener('keydown', onKey, true);
    document.addEventListener('keydown', onKey, true);
    if (containerRef.current) {
      containerRef.current.focus();
    }
    return () => {
      window.removeEventListener('keydown', onKey, true);
      document.removeEventListener('keydown', onKey, true);
    };
  }, []);

  // Focus container on mount to capture keyboard events
  useEffect(() => {
    // Small delay to ensure DOM is ready
    const timer = setTimeout(() => {
      if (containerRef.current) {
        containerRef.current.focus();
      }
    }, 100);
    return () => clearTimeout(timer);
  }, []);

  // Fullscreen is opt-in. Default mode is "full window" — the fixed-position
  // portal already covers 100vw × 100vh, like Google Slides' Slideshow view.
  // Users can toggle true browser fullscreen via the F key or the toolbar
  // button (matches Google Slides' Cmd+Shift+Enter).
  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  };
  const toggleFullscreenRef = useRef(toggleFullscreen);
  toggleFullscreenRef.current = toggleFullscreen;

  useEffect(() => {
    const handleFullscreenChange = () => {
      const fs = !!document.fullscreenElement;
      setIsFullscreen(fs);
      // Recalculate scale: viewport changes shape when toggling fullscreen.
      // Refocus the container so keyboard nav keeps working.
      setTimeout(() => {
        const baseWidth = 1280;
        const baseHeight = 720;
        const newScale = Math.min(
          window.innerWidth / baseWidth,
          window.innerHeight / baseHeight,
        );
        setScale(newScale);
        if (containerRef.current) {
          containerRef.current.focus();
        }
      }, 50);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      // If we were holding the browser fullscreen lock, release it on unmount.
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      }
    };
  }, []);

  // In fullscreen the slides own the screen — toolbar, hint, and counter all
  // hide. Keyboard shortcuts (Esc, F, arrows) still work. Full-window mode
  // keeps the interactive toolbar + counter visible because that's still a
  // "preview" surface.
  const controlsVisible = !isFullscreen;

  // The keyboard-shortcut hint is purely educational. Show it for a few
  // seconds on mount so the user can learn the controls, then fade it out so
  // it stops covering slide content. Stays hidden afterwards.
  const [hintVisible, setHintVisible] = useState(true);
  useEffect(() => {
    const t = setTimeout(() => setHintVisible(false), 3000);
    return () => clearTimeout(t);
  }, []);

  // Handle iframe load — refocus the container, AND attach the keydown
  // handler to the iframe's freshly-loaded contentDocument so navigation works
  // even when focus lands inside the iframe (which happens after tab switch,
  // re-entering fullscreen, or clicking on slide content). srcdoc reloads
  // create a new contentDocument each time, so we re-attach per load; the old
  // document is GC'd along with its listener.
  const handleIframeLoad = () => {
    if (containerRef.current) {
      containerRef.current.focus();
    }
    const doc = iframeRef.current?.contentDocument;
    if (doc) {
      const onKey = (e: KeyboardEvent) => handleKeyDownRef.current(e);
      doc.addEventListener('keydown', onKey, true);
    }
  };

  return createPortal(
    <div
      ref={containerRef}
      tabIndex={-1}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 9999,
        backgroundColor: '#000000',
        margin: 0,
        padding: 0,
        overflow: 'hidden',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        outline: 'none', // Remove focus outline
      }}
    >
      {/* Slide counter overlay */}
      <div
        style={{
          position: 'absolute',
          bottom: '20px',
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          color: '#ffffff',
          padding: '8px 16px',
          borderRadius: '8px',
          fontSize: '14px',
          fontFamily: 'system-ui, sans-serif',
          zIndex: 10000,
          pointerEvents: 'none',
          opacity: controlsVisible ? 1 : 0,
          transition: 'opacity 0.2s ease-out',
        }}
      >
        {currentSlideIndex + 1} / {slideCount}
      </div>

      {/* Toolbar: fullscreen toggle + close button. Discoverable equivalents
          of the F and Esc keyboard shortcuts. Auto-hides in fullscreen. */}
      <div
        style={{
          position: 'absolute',
          top: '20px',
          right: '20px',
          display: 'flex',
          gap: '8px',
          zIndex: 10000,
          opacity: controlsVisible ? 1 : 0,
          // While hidden, swallow pointer events so the user can't accidentally
          // click an invisible button.
          pointerEvents: controlsVisible ? 'auto' : 'none',
          transition: 'opacity 0.2s ease-out',
        }}
      >
        <button
          type="button"
          onClick={toggleFullscreen}
          aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
          title={isFullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}
          data-testid="presentation-fullscreen-toggle"
          style={{
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            color: '#ffffff',
            width: '36px',
            height: '36px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          {isFullscreen ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M8 3v3a2 2 0 0 1-2 2H3" />
              <path d="M21 8h-3a2 2 0 0 1-2-2V3" />
              <path d="M3 16h3a2 2 0 0 1 2 2v3" />
              <path d="M16 21v-3a2 2 0 0 1 2-2h3" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 8V5a2 2 0 0 1 2-2h3" />
              <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
              <path d="M3 16v3a2 2 0 0 0 2 2h3" />
              <path d="M21 16v3a2 2 0 0 1-2 2h-3" />
            </svg>
          )}
        </button>
        <button
          type="button"
          onClick={() => onExitRef.current()}
          aria-label="Exit presentation"
          title="Exit (Esc)"
          data-testid="presentation-close"
          style={{
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            color: '#ffffff',
            width: '36px',
            height: '36px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M18 6L6 18" />
            <path d="M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Navigation hint overlay — only shown briefly on open in full-window
          mode so the user learns the keyboard shortcuts, then fades out so it
          stops covering slide content. Stays hidden in fullscreen. */}
      <div
        style={{
          position: 'absolute',
          top: '20px',
          left: '20px',
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          color: '#ffffff',
          padding: '8px 12px',
          borderRadius: '8px',
          fontSize: '12px',
          fontFamily: 'system-ui, sans-serif',
          zIndex: 10000,
          pointerEvents: 'none',
          opacity: controlsVisible && hintVisible ? 0.7 : 0,
          transition: 'opacity 0.4s ease-out',
        }}
      >
        ← → Navigate · F Fullscreen · Esc Exit
      </div>

      {/* Iframe wrapper that maintains 16:9 aspect ratio and scales to fit viewport */}
      <div
        ref={wrapperRef}
        style={{
          width: '100vw',
          height: '100vh',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          position: 'relative',
        }}
      >
        <iframe
          ref={iframeRef}
          srcDoc={currentSlideHTML}
          tabIndex={-1}
          style={{
            width: '1280px',
            height: '720px',
            border: 'none',
            display: 'block',
            margin: 0,
            padding: 0,
            pointerEvents: 'auto',
            transform: `scale(${scale})`,
            // Keep the scaled iframe centered. Truncation of slide CONTENT is
            // handled inside the iframe via .slide-container overflow:hidden;
            // transformOrigin here only controls how the unavoidable empty
            // space (when viewport aspect ratio ≠ 16:9) is distributed.
            // center-center splits it top+bottom equally — biasing to top
            // visually pins the slide to the bottom of the viewport.
            transformOrigin: 'center center',
          }}
          sandbox="allow-scripts allow-same-origin"
          title={`Slide ${currentSlideIndex + 1}`}
          onLoad={handleIframeLoad}
        />
      </div>
    </div>,
    document.body
  );
};

