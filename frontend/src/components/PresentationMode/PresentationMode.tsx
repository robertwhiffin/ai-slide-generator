import { useEffect, useMemo, useRef } from 'react';
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
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Focus iframe when loaded so keyboard events work
  const handleIframeLoad = () => {
    iframeRef.current?.focus();
    // Debug: log generated HTML to console
    console.log('[PresentationMode] Generated HTML:', generatedHTML);
    console.log('[PresentationMode] Slide count:', slideDeck.slides.length);
    console.log('[PresentationMode] External scripts:', slideDeck.external_scripts);
    console.log('[PresentationMode] CSS length:', slideDeck.css.length);
    console.log('[PresentationMode] Scripts length:', slideDeck.scripts.length);
  };

  // Handle fullscreen and exit on Escape
  useEffect(() => {
    document.documentElement.requestFullscreen().catch(() => {
      // Fallback: still show presentation if fullscreen denied
    });

    const handleFullscreenChange = () => {
      if (!document.fullscreenElement) {
        onExit();
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

  // Generate the iframe HTML with reveal.js
  const generatedHTML = useMemo(() => {
    const slidesHtml = slideDeck.slides
      .map((slide) => `<section>${slide.html}</section>`)
      .join('\n');

    const externalScriptsHtml = slideDeck.external_scripts
      .map((src) => `<script src="${src}"></script>`)
      .join('\n');

    return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/white.css">
  ${externalScriptsHtml}
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #000;
    }
    .reveal-viewport {
      display: flex;
      justify-content: center;
      align-items: center;
      width: 100%;
      height: 100%;
    }
    .reveal {
      width: 100%;
      height: 100%;
    }
    .reveal .slides {
      text-align: left;
    }
    .reveal .slides section {
      height: 100%;
      width: 100%;
      padding: 0;
      box-sizing: border-box;
    }
    /* Override slide internal styling for presentation mode */
    .reveal .slides section .slide {
      width: 100% !important;
      height: 100% !important;
      min-height: 100% !important;
      max-height: 100% !important;
      position: relative;
      box-sizing: border-box;
    }
    /* Ensure charts resize properly */
    .reveal canvas {
      max-width: 100%;
    }
    /* Neutralize reveal.js typography styles so slide CSS takes precedence */
    .reveal .slides section h1,
    .reveal .slides section h2,
    .reveal .slides section h3,
    .reveal .slides section h4,
    .reveal .slides section h5,
    .reveal .slides section h6 {
      font-size: inherit;
      font-weight: inherit;
      line-height: inherit;
      margin: 0;
      text-transform: none;
      color: inherit;
      text-shadow: none;
    }
    .reveal .slides section p {
      font-size: inherit;
      line-height: inherit;
      margin: 0;
    }
    .reveal .slides section ul,
    .reveal .slides section ol {
      margin: 0;
      padding: 0;
    }
    .reveal .slides section a {
      color: inherit;
    }
    ${slideDeck.css}
  </style>
</head>
<body>
  <div class="reveal-viewport">
    <div class="reveal">
      <div class="slides">
        ${slidesHtml}
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
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
          console.error('Chart.js failed to load');
        }
      };
      check();
    }

    function initializeCharts() {
      console.log('[PresentationMode] Initializing charts...');
      try {
        ${slideDeck.scripts}
        console.log('[PresentationMode] Charts initialized successfully');
      } catch (err) {
        console.error('[PresentationMode] Chart initialization error:', err);
      }
    }

    Reveal.initialize({
      hash: false,
      controls: true,
      progress: true,
      slideNumber: true,
      overview: false,
      keyboard: { 27: null },
      width: 1280,
      height: 720,
      margin: 0,
      minScale: 0.1,
      maxScale: 2.0,
      center: true,
      embedded: false,
      transition: 'slide',
      display: 'flex'
    }).then(() => {
      console.log('[PresentationMode] Reveal.js initialized');
      Reveal.slide(${startIndex});
      
      // Initialize charts after reveal.js is ready
      waitForChartJs(initializeCharts);
    });
  </script>
</body>
</html>`;
  }, [slideDeck, startIndex]);

  return createPortal(
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 9999,
        backgroundColor: 'black',
        margin: 0,
        padding: 0,
        overflow: 'hidden',
      }}
    >
      <iframe
        ref={iframeRef}
        srcDoc={generatedHTML}
        style={{
          width: '100%',
          height: '100%',
          border: 'none',
          display: 'block',
          margin: 0,
          padding: 0,
        }}
        sandbox="allow-scripts allow-same-origin"
        title="Presentation"
        onLoad={handleIframeLoad}
      />
    </div>,
    document.body
  );
};

