/**
 * Client-side PPTX export utilities.
 * Captures Chart.js canvas screenshots before sending to backend.
 */

import type { SlideDeck } from '../types/slide';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

/**
 * Build HTML for a single slide (same as PDF client).
 */
function buildSlideHTML(slideDeck: SlideDeck, slideIndex: number): string {
  const slide = slideDeck.slides[slideIndex];
  const externalScripts = slideDeck.external_scripts
    .map((src) => `    <script src="${src}"></script>`)
    .join('\n');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${slideDeck.title || 'Slide Deck'} - Slide ${slideIndex + 1}</title>
${externalScripts}
  <style>
    html, body {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    html {
      width: ${SLIDE_WIDTH}px;
      height: ${SLIDE_HEIGHT}px;
      overflow: hidden;
    }
    body {
      margin: 0 !important;
      padding: 0 !important;
      width: ${SLIDE_WIDTH}px !important;
      height: ${SLIDE_HEIGHT}px !important;
      overflow: hidden !important;
      position: relative;
    }
    ${slideDeck.css}
  </style>
</head>
<body>
${slide.html}
  <script>
    // Wait for Chart.js to be available before running chart initialization scripts
    function waitForChartJs(callback, maxAttempts = 50) {
      let attempts = 0;
      const check = () => {
        attempts++;
        if (typeof Chart !== 'undefined') {
          callback();
        } else if (attempts < maxAttempts) {
          setTimeout(check, 100);
        } else {
          console.error('[CAPTURE] Chart.js failed to load');
        }
      };
      check();
    }

    function initializeCharts() {
      console.log('[CAPTURE] Initializing charts...');
      try {
        // First, destroy any existing Chart.js instances to avoid "canvas already in use" errors
        if (typeof Chart !== 'undefined' && Chart.getChart) {
          const canvases = document.querySelectorAll('canvas');
          canvases.forEach((canvas) => {
            const existingChart = Chart.getChart(canvas);
            if (existingChart) {
              console.log('[CAPTURE] Destroying existing chart on canvas:', canvas.id || 'unnamed');
              existingChart.destroy();
            }
          });
        }
        
        // Now initialize charts
        ${slideDeck.scripts}
        console.log('[CAPTURE] Charts initialized successfully');
      } catch (err) {
        console.error('[CAPTURE] Chart initialization error:', err);
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
}

/**
 * Wait for Chart.js charts to render in an iframe.
 */
async function waitForChartsToRender(
  iframeDoc: Document,
  iframeWindow: Window | null,
  maxWait: number = 10000
): Promise<void> {
  if (!iframeWindow) return;
  
  const startTime = Date.now();
  
  // First, wait for Chart.js library to load
  const iframeWindowAny = iframeWindow as any;
  while (typeof iframeWindowAny.Chart === 'undefined' && Date.now() - startTime < maxWait) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  
  if (typeof iframeWindowAny.Chart === 'undefined') {
    console.warn('Chart.js not loaded in iframe');
    return;
  }
  
  // Find all canvas elements
  const canvases = iframeDoc.querySelectorAll('canvas');
  if (canvases.length === 0) {
    // No charts, consider ready
    await new Promise((resolve) => setTimeout(resolve, 500));
    return;
  }
  
  // Wait for canvases to have dimensions (indicating they're rendered)
  let allHaveDimensions = false;
  let attempts = 0;
  const maxAttempts = 50; // 5 seconds max (50 * 100ms)
  
  while (!allHaveDimensions && attempts < maxAttempts && Date.now() - startTime < maxWait) {
    allHaveDimensions = Array.from(canvases).every((canvas) => {
      return (canvas as HTMLCanvasElement).width > 0 && (canvas as HTMLCanvasElement).height > 0;
    });
    
    if (!allHaveDimensions) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      attempts++;
    }
  }
  
  // Now wait for charts to have actual content (pixels drawn)
  let allReady = false;
  attempts = 0;
  const maxContentAttempts = 50; // 5 seconds max (50 * 100ms) - increased for slower charts
  
  while (!allReady && attempts < maxContentAttempts && Date.now() - startTime < maxWait) {
    allReady = true;
    for (let i = 0; i < canvases.length; i++) {
      const canvas = canvases[i] as HTMLCanvasElement;
      const ctx = canvas.getContext('2d');
      if (ctx && canvas.width > 0 && canvas.height > 0) {
        try {
          // Check a larger sample area - use more of the canvas for better detection
          const sampleWidth = Math.min(canvas.width, 400);
          const sampleHeight = Math.min(canvas.height, 400);
          const imageData = ctx.getImageData(0, 0, sampleWidth, sampleHeight);
          const data = imageData.data;
          let hasContent = false;
          let pixelCount = 0;
          // Check if there are any non-transparent pixels
          for (let j = 3; j < data.length; j += 4) {
            if (data[j] > 0) {
              hasContent = true;
              pixelCount++;
            }
          }
          // Need at least 100 pixels to be drawn (charts should have many more)
          // Lower threshold to catch charts that are still rendering
          if (!hasContent || pixelCount < 100) {
            allReady = false;
            if (attempts % 10 === 0) {
              console.log(`[CAPTURE] Canvas ${i} not ready yet: ${pixelCount} pixels (need 100+)`);
            }
            break;
          }
        } catch (e) {
          allReady = false;
          break;
        }
      } else {
        allReady = false;
        break;
      }
    }
    
    if (!allReady) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      attempts++;
    }
  }
  
  if (allReady) {
    // Wait a bit more to ensure everything is fully rendered and animations complete
    await new Promise((resolve) => setTimeout(resolve, 1000));
  } else {
    console.warn(`[CAPTURE] Some charts may not be fully ready after ${attempts * 100}ms`);
  }
}

/**
 * Capture Chart.js canvas screenshots from a slide.
 * Returns a map of canvas IDs/indexes to base64 PNG data URLs.
 */
async function captureSlideCharts(
  slideDeck: SlideDeck,
  slideIndex: number
): Promise<Record<string, string>> {
  console.log(`[CAPTURE] Slide ${slideIndex + 1}: Starting capture`);
  
  // Create hidden iframe to render the slide
  const iframe = document.createElement('iframe');
  iframe.style.position = 'absolute';
  iframe.style.left = '-9999px';
  iframe.style.top = '-9999px';
  iframe.style.width = `${SLIDE_WIDTH}px`;
  iframe.style.height = `${SLIDE_HEIGHT}px`;
  iframe.style.border = 'none';
  
  const iframeContainer = document.createElement('div');
  iframeContainer.style.position = 'absolute';
  iframeContainer.style.left = '-9999px';
  iframeContainer.style.top = '-9999px';
  iframeContainer.style.width = `${SLIDE_WIDTH}px`;
  iframeContainer.style.height = `${SLIDE_HEIGHT}px`;
  iframeContainer.appendChild(iframe);
  document.body.appendChild(iframeContainer);

  try {
    // Build HTML for this slide
    const slideHTML = buildSlideHTML(slideDeck, slideIndex);
    const slide = slideDeck.slides[slideIndex];
    const hasCanvasInSlide = slide.html.includes('<canvas');
    const hasScriptInSlide = slide.html.includes('<script');
    console.log(`[CAPTURE] Slide ${slideIndex + 1}: Built HTML (${slideHTML.length} chars)`);
    console.log(`[CAPTURE] Slide ${slideIndex + 1}: Slide HTML has <canvas: ${hasCanvasInSlide}, has <script: ${hasScriptInSlide}`);
    console.log(`[CAPTURE] Slide ${slideIndex + 1}: Built HTML has <canvas: ${slideHTML.includes('<canvas')}, has <script: ${slideHTML.includes('<script')}`);
    
    // Set iframe content
    iframe.srcdoc = slideHTML;

    // Wait for iframe to load
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Iframe load timeout'));
      }, 15000);

      iframe.onload = () => {
        clearTimeout(timeout);
        resolve();
      };

      iframe.onerror = () => {
        clearTimeout(timeout);
        reject(new Error('Iframe load error'));
      };
    });

    // Get iframe document and window
    const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
    const iframeWindow = iframe.contentWindow;
    
    if (!iframeDoc || !iframeWindow) {
      throw new Error('Cannot access iframe document');
    }

    // Wait for external scripts to load (Chart.js from CDN)
    console.log(`[CAPTURE] Slide ${slideIndex + 1}: Waiting for external scripts to load...`);
    let chartJsLoaded = false;
    const iframeWindowAny = iframeWindow as any;
    for (let waitAttempt = 0; waitAttempt < 20; waitAttempt++) {
      if (typeof iframeWindowAny.Chart !== 'undefined') {
        chartJsLoaded = true;
        console.log(`[CAPTURE] Slide ${slideIndex + 1}: Chart.js loaded after ${waitAttempt * 100}ms`);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    
    if (!chartJsLoaded) {
      console.error(`[CAPTURE] Slide ${slideIndex + 1}: Chart.js failed to load after 2 seconds!`);
    }
    
    // Scripts in the HTML should have already executed when the iframe loaded
    // The buildSlideHTML function includes slideDeck.scripts which will initialize charts
    // We just need to wait for them to finish rendering
    console.log(`[CAPTURE] Slide ${slideIndex + 1}: Waiting for charts to initialize...`);
    
    // Wait for Chart.js charts to render (this now includes Chart.js loading check)
    await waitForChartsToRender(iframeDoc, iframeWindow, 20000);
    
    // Additional wait to ensure charts are fully painted and animations complete
    await new Promise((resolve) => setTimeout(resolve, 2000));
    
    // Force a reflow to ensure everything is painted
    iframeDoc.body.offsetHeight;

    // Capture all canvas elements
    const chartImages: Record<string, string> = {};
    const canvases = iframeDoc.querySelectorAll('canvas');
    console.log(`[CAPTURE] Slide ${slideIndex + 1}: Found ${canvases.length} canvas elements`);
    
    if (canvases.length === 0) {
      console.warn(`[CAPTURE] Slide ${slideIndex + 1}: No canvas elements found in iframe`);
      // Check if HTML has canvas tags
      const htmlHasCanvas = iframeDoc.body.innerHTML.includes('<canvas');
      console.log(`[CAPTURE] Slide ${slideIndex + 1}: HTML contains <canvas: ${htmlHasCanvas}`);
    }
    
    for (let i = 0; i < canvases.length; i++) {
      const canvas = canvases[i] as HTMLCanvasElement;
      try {
        // Verify canvas has dimensions
        if (canvas.width === 0 || canvas.height === 0) {
          console.warn(`Canvas ${i} has zero dimensions, skipping`);
          continue;
        }
        
        // Verify canvas has content before capturing
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          console.warn(`Canvas ${i} has no context, skipping`);
          continue;
        }
        
        // Check if canvas has actual content (not blank)
        try {
          const sampleWidth = Math.min(canvas.width, 200);
          const sampleHeight = Math.min(canvas.height, 200);
          const imageData = ctx.getImageData(0, 0, sampleWidth, sampleHeight);
          const data = imageData.data;
          let pixelCount = 0;
          // Count non-transparent pixels
          for (let j = 3; j < data.length; j += 4) {
            if (data[j] > 0) {
              pixelCount++;
            }
          }
          
          // Need at least 100 pixels to be drawn (charts should have many more)
          if (pixelCount < 100) {
            console.warn(`Canvas ${i} has only ${pixelCount} pixels, likely blank, skipping`);
            continue;
          }
        } catch (e) {
          console.warn(`Canvas ${i} content check failed: ${e}, skipping`);
          continue;
        }
        
        // Use canvas.toDataURL() for Chart.js charts
        const dataUrl = canvas.toDataURL('image/png');
        
        // Verify the image isn't blank (check data URL length - blank images are typically < 2000 chars)
        if (dataUrl.length < 2000) {
          console.warn(`Canvas ${i} produced suspiciously small data URL (${dataUrl.length} chars), likely blank, skipping`);
          continue;
        }
        
        // Use canvas ID if available, otherwise use index
        const canvasId = canvas.id || `chart_${i}`;
        chartImages[canvasId] = dataUrl;
        console.log(`✓ Captured canvas ${i} (${canvasId}): ${canvas.width}x${canvas.height}, data URL length: ${dataUrl.length} chars`);
      } catch (error) {
        console.warn(`Failed to capture canvas ${i}:`, error);
      }
    }

    return chartImages;
  } finally {
    // Cleanup
    document.body.removeChild(iframeContainer);
  }
}

/**
 * Capture Chart.js screenshots for all slides in a deck.
 * Returns an array of maps, one per slide, with canvas IDs to base64 PNG data URLs.
 */
export async function captureSlideDeckCharts(
  slideDeck: SlideDeck
): Promise<Array<Record<string, string>>> {
  console.log(`[CAPTURE] Starting capture for ${slideDeck.slides.length} slides`);
  const allChartImages: Array<Record<string, string>> = [];
  
  for (let i = 0; i < slideDeck.slides.length; i++) {
    try {
      console.log(`[CAPTURE] Processing slide ${i + 1}/${slideDeck.slides.length}`);
      const chartImages = await captureSlideCharts(slideDeck, i);
      console.log(`[CAPTURE] Slide ${i + 1}: Captured ${Object.keys(chartImages).length} charts (IDs: ${Object.keys(chartImages).join(', ') || 'none'})`);
      allChartImages.push(chartImages);
    } catch (error) {
      console.error(`[CAPTURE] Failed to capture charts for slide ${i + 1}:`, error);
      console.error(`[CAPTURE] Error details:`, error instanceof Error ? error.stack : String(error));
      allChartImages.push({}); // Empty map for this slide
    }
  }
  
  const totalCharts = allChartImages.reduce((sum, slide) => sum + Object.keys(slide).length, 0);
  console.log(`[CAPTURE] Completed: ${totalCharts} total charts captured across ${slideDeck.slides.length} slides`);
  
  return allChartImages;
}

