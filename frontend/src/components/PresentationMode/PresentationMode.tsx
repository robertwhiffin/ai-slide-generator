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
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Generate HTML for current slide (no reveal.js)
  const currentSlideHTML = useMemo(() => {
    const slide = slideDeck.slides[currentSlideIndex];
    const slideScripts = slide.scripts || '';
    
    const externalScriptsHtml = slideDeck.external_scripts
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
      align-items: flex-start;
      padding: 20px;
    }
    /* Slide container - maintains 16:9 aspect ratio, scales to fit viewport */
    .slide-container {
      width: 1280px;
      height: 720px;
      max-width: 100vw;
      max-height: 100vh;
      position: relative;
      background: #ffffff;
      overflow: auto;
      margin: auto;
    }
    /* Ensure slide content fills container */
    .slide-container > * {
      width: 100%;
      height: 100%;
    }
    /* Chart canvas scaling */
    canvas {
      max-width: 100%;
      height: auto;
    }
    ${slideDeck.css}
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
  }, [currentSlideIndex, slideDeck]);

  // Update iframe content when slide changes
  useEffect(() => {
    if (iframeRef.current) {
      iframeRef.current.srcdoc = currentSlideHTML;
    }
  }, [currentSlideHTML]);

  // Handle keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle if not typing in an input/textarea
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      switch (e.key) {
        case 'ArrowRight':
        case 'ArrowDown':
        case ' ': // Spacebar
          e.preventDefault();
          e.stopPropagation();
          setCurrentSlideIndex((prev) => Math.min(prev + 1, slideDeck.slides.length - 1));
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
          setCurrentSlideIndex(slideDeck.slides.length - 1);
          break;
        case 'Escape':
          e.preventDefault();
          e.stopPropagation();
          onExit();
          break;
      }
    };

    // Attach to both window and document for better coverage
    window.addEventListener('keydown', handleKeyDown, true); // Use capture phase
    document.addEventListener('keydown', handleKeyDown, true);
    
    // Focus the container to ensure keyboard events are captured
    if (containerRef.current) {
      containerRef.current.focus();
    }

    return () => {
      window.removeEventListener('keydown', handleKeyDown, true);
      document.removeEventListener('keydown', handleKeyDown, true);
    };
  }, [slideDeck.slides.length, onExit]);

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

  // Handle fullscreen
  useEffect(() => {
    document.documentElement.requestFullscreen().catch(() => {
      // Fallback: still show presentation if fullscreen denied
    });

    const handleFullscreenChange = () => {
      if (!document.fullscreenElement) {
        onExit();
      } else {
        // Refocus container when entering fullscreen
        setTimeout(() => {
          if (containerRef.current) {
            containerRef.current.focus();
          }
        }, 100);
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      if (document.fullscreenElement) {
        document.exitFullscreen();
      }
    };
  }, [onExit]);

  // Handle iframe load - refocus container to capture keyboard events
  const handleIframeLoad = () => {
    // Don't focus iframe, keep focus on container for keyboard navigation
    if (containerRef.current) {
      containerRef.current.focus();
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
        overflow: 'auto',
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
        }}
      >
        {currentSlideIndex + 1} / {slideDeck.slides.length}
      </div>

      {/* Navigation hint overlay */}
      <div
        style={{
          position: 'absolute',
          top: '20px',
          right: '20px',
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          color: '#ffffff',
          padding: '8px 12px',
          borderRadius: '8px',
          fontSize: '12px',
          fontFamily: 'system-ui, sans-serif',
          zIndex: 10000,
          pointerEvents: 'none',
          opacity: 0.7,
        }}
      >
        ← → Navigate | ESC Exit
      </div>

      {/* Single iframe that updates content */}
      <iframe
        ref={iframeRef}
        srcDoc={currentSlideHTML}
        tabIndex={-1}
        style={{
          width: '100%',
          height: '100%',
          border: 'none',
          display: 'block',
          margin: 0,
          padding: 0,
          pointerEvents: 'auto', // Allow interactions within iframe
        }}
        sandbox="allow-scripts allow-same-origin"
        title={`Slide ${currentSlideIndex + 1}`}
        onLoad={handleIframeLoad}
      />
    </div>,
    document.body
  );
};

