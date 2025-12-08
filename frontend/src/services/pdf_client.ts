/**
 * Client-side PDF generation service.
 * Uses jsPDF and html2canvas to convert slide decks to PDF without server-side binaries.
 */

import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';
import type { SlideDeck } from '../types/slide';

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;

/**
 * Build HTML for a single slide.
 * Matches the structure used in SlideTile for consistent rendering.
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
    * {
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
    // Wrap scripts in try-catch to handle chart initialization
    try {
      ${slideDeck.scripts}
    } catch (error) {
      console.debug('Chart initialization error:', error.message);
    }
  </script>
</body>
</html>`;
}

/**
 * Wait for Chart.js charts to be fully rendered in the iframe.
 */
async function waitForChartsToRender(
  iframeDoc: Document,
  iframeWindow: Window | null,
  maxWait: number = 10000
): Promise<void> {
  if (!iframeWindow) return;

  const startTime = Date.now();
  
  // First, wait for Chart.js library to load
  // Use type assertion to access Chart property
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
    // No charts to wait for
    return;
  }

  // Wait for canvases to have dimensions (indicating they're rendered)
  let allReady = false;
  let attempts = 0;
  const maxAttempts = 50; // 5 seconds max (50 * 100ms)

  while (!allReady && attempts < maxAttempts && Date.now() - startTime < maxWait) {
    allReady = Array.from(canvases).every((canvas) => {
      return canvas.width > 0 && canvas.height > 0;
    });

    if (!allReady) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      attempts++;
    }
  }

  // Additional wait to ensure charts are fully painted
  if (allReady) {
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

/**
 * Export slide deck as PDF using client-side generation.
 * No server-side binaries required.
 * Renders each slide individually using iframe to ensure Chart.js loads correctly.
 *
 * @param slideDeck - The slide deck to export
 * @param filename - Optional filename (default: slides.pdf)
 * @param options - PDF export options
 */
export async function exportSlideDeckToPDF(
  slideDeck: SlideDeck,
  filename: string = 'slides.pdf',
  options: {
    format?: 'a4' | 'letter';
    orientation?: 'portrait' | 'landscape';
    scale?: number;
    waitForCharts?: number;
    imageQuality?: number; // JPEG quality 0-1 (default: 0.85)
  } = {}
): Promise<void> {
  const {
    format = 'a4',
    orientation = 'landscape',
    scale = 1.2, // Optimized: 1.2x provides good quality without huge file size
    waitForCharts = 5000, // Wait up to 5 seconds for Chart.js to render
    imageQuality = 0.85, // JPEG quality: 0.85 provides good balance
  } = options;

  // Create PDF document
  const pdf = new jsPDF({
    orientation: orientation === 'landscape' ? 'l' : 'p',
    unit: 'mm',
    format: format,
  });

  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();

  // Process each slide individually
  for (let i = 0; i < slideDeck.slides.length; i++) {
    // Create iframe container (completely hidden)
    const iframeContainer = document.createElement('div');
    iframeContainer.style.position = 'fixed';
    iframeContainer.style.left = '-99999px';
    iframeContainer.style.top = '0';
    iframeContainer.style.width = `${SLIDE_WIDTH}px`;
    iframeContainer.style.height = `${SLIDE_HEIGHT}px`;
    iframeContainer.style.visibility = 'hidden';
    iframeContainer.style.opacity = '0';
    iframeContainer.style.pointerEvents = 'none';
    iframeContainer.style.zIndex = '-9999';
    iframeContainer.style.overflow = 'hidden';

    // Create iframe for rendering (better for external scripts)
    const iframe = document.createElement('iframe');
    iframe.style.width = `${SLIDE_WIDTH}px`;
    iframe.style.height = `${SLIDE_HEIGHT}px`;
    iframe.style.border = 'none';
    iframe.style.display = 'block';
    iframe.style.margin = '0';
    iframe.style.padding = '0';
    
    iframeContainer.appendChild(iframe);
    document.body.appendChild(iframeContainer);

    try {
      // Build HTML for this slide
      const slideHTML = buildSlideHTML(slideDeck, i);
      
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
      
      if (!iframeDoc) {
        throw new Error('Cannot access iframe document');
      }

      // Wait for external scripts to load
      await new Promise((resolve) => setTimeout(resolve, 1000));

      // Wait for Chart.js charts to render
      await waitForChartsToRender(iframeDoc, iframeWindow, waitForCharts);

      // Additional wait for first slide to ensure full rendering
      // First slide often needs extra time for fonts and layout to settle
      if (i === 0) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        // Force a reflow to ensure layout is complete
        iframeDoc.body.offsetHeight;
      }

      // Ensure document has exact dimensions
      iframeDoc.documentElement.style.width = `${SLIDE_WIDTH}px`;
      iframeDoc.documentElement.style.height = `${SLIDE_HEIGHT}px`;
      iframeDoc.documentElement.style.overflow = 'hidden';
      iframeDoc.documentElement.style.margin = '0';
      iframeDoc.documentElement.style.padding = '0';

      iframeDoc.body.style.margin = '0';
      iframeDoc.body.style.padding = '0';
      iframeDoc.body.style.width = `${SLIDE_WIDTH}px`;
      iframeDoc.body.style.height = `${SLIDE_HEIGHT}px`;
      iframeDoc.body.style.overflow = 'hidden';
      iframeDoc.body.style.position = 'relative';
      iframeDoc.body.style.boxSizing = 'border-box';

      // Find the first child element (usually the slide content)
      // If there's a .slide element, use that; otherwise use body
      const slideElement = iframeDoc.querySelector('.slide') || iframeDoc.body;
      
      // Ensure slide element has exact dimensions but preserve its padding
      // Don't remove padding - slides typically have padding: 60px 80px for proper spacing
      if (slideElement && slideElement !== iframeDoc.body) {
        const slideEl = slideElement as HTMLElement;
        // Only set width/height, don't override padding or position
        slideEl.style.width = `${SLIDE_WIDTH}px`;
        slideEl.style.height = `${SLIDE_HEIGHT}px`;
        slideEl.style.margin = '0';
        slideEl.style.boxSizing = 'border-box';
        // Don't set position: absolute or remove padding - preserve original layout
      }

      // Ensure element is fully rendered before capture
      // Force layout recalculation
      const slideEl = slideElement as HTMLElement;
      slideEl.offsetHeight; // Force reflow
      
      // Convert slide element to canvas with exact dimensions
      const canvas = await html2canvas(slideEl, {
        width: SLIDE_WIDTH,
        height: SLIDE_HEIGHT,
        scale: scale,
        useCORS: true,
        logging: false,
        backgroundColor: null, // Use slide's background
        windowWidth: SLIDE_WIDTH,
        windowHeight: SLIDE_HEIGHT,
        allowTaint: false,
        x: 0,
        y: 0,
        scrollX: 0,
        scrollY: 0,
        removeContainer: false, // Keep container for first slide
        // Ensure cloned document has exact dimensions but preserve slide padding
        onclone: (clonedDoc) => {
          const clonedHtml = clonedDoc.documentElement;
          const clonedBody = clonedDoc.body;
          
          clonedHtml.style.width = `${SLIDE_WIDTH}px`;
          clonedHtml.style.height = `${SLIDE_HEIGHT}px`;
          clonedHtml.style.overflow = 'hidden';
          clonedHtml.style.margin = '0';
          clonedHtml.style.padding = '0';
          
          clonedBody.style.width = `${SLIDE_WIDTH}px`;
          clonedBody.style.height = `${SLIDE_HEIGHT}px`;
          clonedBody.style.overflow = 'hidden';
          clonedBody.style.margin = '0';
          clonedBody.style.padding = '0';
          clonedBody.style.position = 'relative';
          clonedBody.style.boxSizing = 'border-box';
          
          // Preserve .slide element's padding if it exists
          const clonedSlide = clonedDoc.querySelector('.slide') as HTMLElement;
          if (clonedSlide) {
            // Don't override padding - preserve original padding from CSS
            clonedSlide.style.width = `${SLIDE_WIDTH}px`;
            clonedSlide.style.height = `${SLIDE_HEIGHT}px`;
            clonedSlide.style.margin = '0';
            clonedSlide.style.boxSizing = 'border-box';
          }
        },
      });

      // Verify canvas dimensions match expected size
      const expectedCanvasWidth = SLIDE_WIDTH * scale;
      const expectedCanvasHeight = SLIDE_HEIGHT * scale;
      
      // If canvas size doesn't match, crop or pad to exact dimensions
      let finalCanvas = canvas;
      const widthDiff = Math.abs(canvas.width - expectedCanvasWidth);
      const heightDiff = Math.abs(canvas.height - expectedCanvasHeight);
      
      if (widthDiff > 5 || heightDiff > 5) {
        // Create a new canvas with exact dimensions
        const adjustedCanvas = document.createElement('canvas');
        adjustedCanvas.width = expectedCanvasWidth;
        adjustedCanvas.height = expectedCanvasHeight;
        const ctx = adjustedCanvas.getContext('2d');
        if (ctx) {
          // Get slide background color from the slide element
          const slideEl = slideElement as HTMLElement;
          const bgColor = window.getComputedStyle(slideEl).backgroundColor || '#ffffff';
          ctx.fillStyle = bgColor;
          ctx.fillRect(0, 0, expectedCanvasWidth, expectedCanvasHeight);
          
          // Calculate source and destination positions
          // If canvas is larger, crop from center; if smaller, center it
          let sourceX = 0;
          let sourceY = 0;
          let sourceWidth = canvas.width;
          let sourceHeight = canvas.height;
          let destX = 0;
          let destY = 0;
          let destWidth = expectedCanvasWidth;
          let destHeight = expectedCanvasHeight;
          
          // If source is larger, crop from center
          if (canvas.width > expectedCanvasWidth) {
            sourceX = (canvas.width - expectedCanvasWidth) / 2;
            sourceWidth = expectedCanvasWidth;
          } else if (canvas.width < expectedCanvasWidth) {
            // If source is smaller, center it
            destX = (expectedCanvasWidth - canvas.width) / 2;
            destWidth = canvas.width;
          }
          
          if (canvas.height > expectedCanvasHeight) {
            sourceY = (canvas.height - expectedCanvasHeight) / 2;
            sourceHeight = expectedCanvasHeight;
          } else if (canvas.height < expectedCanvasHeight) {
            destY = (expectedCanvasHeight - canvas.height) / 2;
            destHeight = canvas.height;
          }
          
          // Draw the captured canvas
          ctx.drawImage(
            canvas,
            sourceX, sourceY, // Source position
            sourceWidth, sourceHeight, // Source size
            destX, destY, // Destination position
            destWidth, destHeight // Destination size
          );
          finalCanvas = adjustedCanvas;
        }
      }

      // Calculate dimensions to fit page while maintaining aspect ratio
      const slideAspectRatio = SLIDE_WIDTH / SLIDE_HEIGHT;
      const pageAspectRatio = pageWidth / pageHeight;

      let imgWidth: number;
      let imgHeight: number;
      let xOffset = 0;
      let yOffset = 0;

      // Use exact slide aspect ratio
      if (slideAspectRatio > pageAspectRatio) {
        // Slide is wider - fit to page width
        imgWidth = pageWidth;
        imgHeight = pageWidth / slideAspectRatio;
        yOffset = (pageHeight - imgHeight) / 2; // Center vertically
      } else {
        // Slide is taller - fit to page height
        imgHeight = pageHeight;
        imgWidth = pageHeight * slideAspectRatio;
        xOffset = (pageWidth - imgWidth) / 2; // Center horizontally
      }

      // Convert final canvas to image data using JPEG for better compression
      const imgData = finalCanvas.toDataURL('image/jpeg', imageQuality);

      // Add new page (except for first slide)
      if (i > 0) {
        pdf.addPage();
      }

      // Add slide image to PDF page
      pdf.addImage(imgData, 'JPEG', xOffset, yOffset, imgWidth, imgHeight);
    } catch (error) {
      console.error(`Failed to export slide ${i + 1}:`, error);
      // Continue with next slide even if one fails
    } finally {
      // Cleanup: remove iframe container
      if (iframeContainer.parentNode) {
        document.body.removeChild(iframeContainer);
      }
    }
  }

  // Download PDF
  pdf.save(filename);
}
