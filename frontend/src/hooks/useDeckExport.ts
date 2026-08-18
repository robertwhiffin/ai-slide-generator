import { useState } from 'react';
import type { SlideDeck } from '../types/slide';
import { api } from '../services/api';
import { exportSlideDeckToPDF } from '../services/pdf_client';
import { useToast } from '../contexts/ToastContext';
import { buildStandaloneDeckDocument } from '../services/slideDocument';

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
        // Partial export must be LOUD: the file is missing slides, so the user
        // gets a persistent error naming exactly which ones failed rather than a
        // soft "see console" notice they will not act on. (Ported from main's
        // pre-refactor SlidePanel; ws6 extracted this into the hook.)
        console.warn('[huashu] per-slide failures:', result.failures);
        const failedSlideNumbers = result.failures
          .map((f) => f.slide_index + 1)
          .sort((a, b) => a - b)
          .join(', ');
        const firstError = result.failures[0]?.error?.split('\n')[0] || 'unknown error';
        showToast(
          `PPTX incomplete: only ${result.succeeded} of ${result.totalSlides} slides exported. ` +
            `Slide${result.failures.length > 1 ? 's' : ''} ${failedSlideNumbers} failed (${firstError}).`,
          'error',
          { persistent: true },
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

    // Delegate to the pure, TESTED builder in slideDocument.ts rather than
    // rebuilding the document inline. main extracted this helper precisely so the
    // layout guarantees could be pinned, and three suites now do pin it
    // (slide-surface-fidelity.spec.ts, slide-host-frame.spec.ts and
    // tests/unit/test_preview_box_model_parity.py). A duplicate here would leave
    // those specs guarding a function the real "Save as HTML" never calls.
    const html = buildStandaloneDeckDocument(slideDeck);

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
