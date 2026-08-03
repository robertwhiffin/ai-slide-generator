import { useState } from 'react';
import type { SlideDeck } from '../types/slide';
import { api } from '../services/api';
import { exportSlideDeckToPDF } from '../services/pdf_client';
import { useToast } from '../contexts/ToastContext';
import { buildSlideDocument } from '../services/slideDocument';

interface UseDeckExportOptions {
  slideDeck: SlideDeck | null;
  sessionId: string | null;
  onExportStatusChange?: (status: string | null) => void;
}

interface UseDeckExportReturn {
  isExportingPDF: boolean;
  isExportingPPTX: boolean;
  handleExportPDF: () => Promise<void>;
  handleExportPPTX: () => Promise<void>;
  handleSaveAsHTML: () => void;
}

export function useDeckExport({
  slideDeck,
  sessionId,
  onExportStatusChange,
}: UseDeckExportOptions): UseDeckExportReturn {
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingPPTX, setIsExportingPPTX] = useState(false);
  const { showToast } = useToast();

  const handleExportPDF = async () => {
    if (!slideDeck || isExportingPDF) return;

    setIsExportingPDF(true);
    onExportStatusChange?.('Exporting PDF...');
    try {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const filename = `${slideDeck.title || 'slides'}_${timestamp}.pdf`;

      await exportSlideDeckToPDF(slideDeck, filename, {
        format: 'a4',
        orientation: 'landscape',
        scale: 1.2,
        waitForCharts: 2000,
        imageQuality: 0.85,
      });
    } catch (error) {
      console.error('PDF export failed:', error);
      const message = error instanceof Error
        ? error.message
        : 'Failed to export PDF. Please try again.';
      alert(message);
    } finally {
      setIsExportingPDF(false);
      onExportStatusChange?.(null);
    }
  };

  const handleExportPPTX = async () => {
    if (!slideDeck || !sessionId || isExportingPPTX) return;

    setIsExportingPPTX(true);
    onExportStatusChange?.('Generating PPTX…');

    const downloadBlob = (blob: Blob, suffix = '') => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const timestamp = new Date().toISOString().slice(0, 10);
      const trailing = suffix ? `_${suffix}` : '';
      a.download = `${slideDeck.title || 'slides'}_${timestamp}${trailing}.pptx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    };

    try {
      // Try the Claude Design path first.
      const result = await api.exportPptxHuashu(sessionId);
      downloadBlob(result.blob);
      onExportStatusChange?.(null);
      if (result.failures.length === 0) {
        showToast(`PPTX downloaded (${result.succeeded}/${result.totalSlides} slides)`, 'success');
      } else {
        // Per-slide failures get logged for the developer; user sees a
        // softer info toast so they know not all slides made it in.
        console.warn('[huashu] per-slide failures:', result.failures);
        showToast(
          `PPTX: ${result.succeeded}/${result.totalSlides} slides exported (${result.failures.length} rejected — see console)`,
          'info',
        );
      }
    } catch (error) {
      // Fallback path: if the Claude Design path isn't bootstrapped on this
      // deployment (returns 503), retry via the records pipeline so the
      // user still gets a working export.
      const status = (error as { status?: unknown })?.status;
      const message = error instanceof Error ? error.message : '';
      const isUnavailable =
        status === 503 ||
        /huashu pipeline not available/i.test(message) ||
        /pipeline (?:still )?installing/i.test(message);
      if (isUnavailable) {
        try {
          onExportStatusChange?.('Falling back to records pipeline (slower)…');
          const blob = await api.exportPptxEditable(slideDeck, sessionId, 'universal');
          downloadBlob(blob);
          onExportStatusChange?.(null);
          showToast('PPTX downloaded (records pipeline)', 'success');
          return;
        } catch (fallbackErr) {
          console.error('PPTX records-fallback export failed:', fallbackErr);
          const fbMsg = fallbackErr instanceof Error ? fallbackErr.message : 'Failed to export PPTX.';
          alert(fbMsg);
          return;
        } finally {
          setIsExportingPPTX(false);
          onExportStatusChange?.(null);
        }
      }
      console.error('PPTX export failed:', error);
      const failures = (error as { failures?: unknown[] })?.failures;
      if (Array.isArray(failures) && failures.length > 0) {
        console.warn('[huashu] per-slide failures (all rejected):', failures);
      }
      alert(message || 'Failed to export PPTX. Please try again.');
    } finally {
      setIsExportingPPTX(false);
      onExportStatusChange?.(null);
    }
  };

  const handleSaveAsHTML = () => {
    if (!slideDeck) return;

    const slidesHtml = slideDeck.slides
      .map((slide, index) => {
        const slideScripts = slide.scripts || '';
        return `
    <div class="slide-wrapper" data-slide-index="${index}">
      <div class="slide-container">
        ${slide.html}
      </div>
      ${slideScripts ? `<script>
        (function() {
          ${slideScripts}
        })();
      </script>` : ''}
    </div>`;
      })
      .join('\n');

    // Multi-slide wrapper/reset layout for the standalone export document.
    const wrapperStyle = `
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    html, body {
      width: 100%;
      height: 100%;
      overflow: auto;
      background: #f9fafb;
    }
    body {
      padding: 40px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 40px;
    }
    .slide-wrapper {
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      page-break-after: always;
    }
    .slide-container {
      width: 1280px;
      height: 720px;
      max-width: 100%;
      max-height: calc(100vh - 80px);
      position: relative;
      background: #ffffff;
      overflow: auto;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      border-radius: 8px;
    }
    .slide-container > * {
      width: 100%;
      min-height: 100%;
    }
    canvas {
      max-width: 100%;
      height: auto;
    }`;

    const bootstrapScripts = `
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
      try {
        ${slideDeck.scripts || ''}
      } catch (err) {
        console.error('Chart initialization error:', err);
      }
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        waitForChartJs(initializeCharts);
      });
    } else {
      waitForChartJs(initializeCharts);
    }`;

    const html = buildSlideDocument(
      `<title>${slideDeck.title || 'Presentation'}</title>\n${slidesHtml}`,
      {
        css: slideDeck.css,
        externalScripts: slideDeck.external_scripts,
        extraHeadStyle: wrapperStyle,
        scripts: bootstrapScripts,
      }
    );

    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(slideDeck.title || 'presentation').replace(/[^a-z0-9]/gi, '-').toLowerCase()}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return {
    isExportingPDF,
    isExportingPPTX,
    handleExportPDF,
    handleExportPPTX,
    handleSaveAsHTML,
  };
}
