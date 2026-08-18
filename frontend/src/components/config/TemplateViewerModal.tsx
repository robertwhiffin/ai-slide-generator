/**
 * Expanded template viewer — a read-only popup that shows a template's slides
 * larger than the card thumbnail allows, paginated when the template ships
 * several slide sections.
 *
 * SECURITY: the uploaded template HTML is USER CONTENT and must never execute
 * against our origin. This component renders NOTHING itself — it delegates
 * entirely to {@link LiveTemplateFrame}, the same renderer the thumbnails use:
 * a fully-sandboxed iframe (`sandbox=""` — no scripts, no same-origin) whose
 * srcDoc carries a strict CSP with network egress BLOCKED, with brand assets
 * already resolved to inline `data:` URIs at serve time. There is no
 * `dangerouslySetInnerHTML` anywhere in this path, and the frame is not
 * granted any additional capability for being bigger.
 *
 * Scope: a VIEWER only — expand, look, close. No editing, no Present mode, no
 * fullscreen slideshow.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import type { DesignSystemTemplate } from '../../api/config';
import { LiveTemplateFrame } from './TemplateThumbnail';

export const TemplateViewerModal: React.FC<{
  dsId: number;
  template: DesignSystemTemplate;
  onClose: () => void;
}> = ({ dsId, template, onClose }) => {
  const [slideCount, setSlideCount] = useState(0);
  const [index, setIndex] = useState(0);

  // A template with 0 or 1 detected sections is a single page.
  const pageCount = Math.max(1, slideCount);
  const isPaginated = pageCount > 1;

  const goPrev = useCallback(
    () => setIndex((i) => (i - 1 + pageCount) % pageCount),
    [pageCount],
  );
  const goNext = useCallback(() => setIndex((i) => (i + 1) % pageCount), [pageCount]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      else if (event.key === 'ArrowLeft') goPrev();
      else if (event.key === 'ArrowRight') goNext();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, goPrev, goNext]);

  // A template whose section count shrinks (re-fetch) must not leave the pager
  // pointing past the end.
  useEffect(() => {
    setIndex((i) => (i < pageCount ? i : 0));
  }, [pageCount]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`${template.name} template preview`}
      data-testid="template-viewer-modal"
    >
      <div className="absolute inset-0 bg-black/60" onClick={onClose} data-testid="template-viewer-backdrop" />

      <div className="relative flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-border bg-background shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-medium text-foreground">{template.name}</h2>
            {template.description && (
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {template.description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close template preview"
            data-testid="template-viewer-close"
            className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* The slide itself: a fixed 16:9 stage the sandboxed frame scales into. */}
        <div className="relative aspect-video w-full overflow-hidden bg-muted/30">
          <LiveTemplateFrame
            dsId={dsId}
            templateId={template.id}
            name={template.name}
            // UNCONDITIONAL, deliberately. Passing `undefined` until the count
            // arrived meant every open built the FULL multi-megabyte document
            // first and then rebuilt the isolated one — TWO navigations, so two
            // white pre-paint windows, on every open. The builder already falls
            // through to the full document when a layout has 0 or 1 slide
            // sections, so this is semantically identical, and on the second
            // render the identical string means React skips the DOM write.
            slideIndex={index}
            onSlideCount={setSlideCount}
            testId="template-viewer-frame"
          />
        </div>

        {isPaginated && (
          <div className="flex items-center justify-center gap-3 border-t border-border px-4 py-2">
            <button
              type="button"
              onClick={goPrev}
              aria-label="Previous slide"
              data-testid="template-viewer-prev"
              className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronLeft className="size-4" />
            </button>
            <span className="text-xs text-muted-foreground" data-testid="template-viewer-counter">
              Slide {index + 1} of {pageCount}
            </span>
            <button
              type="button"
              onClick={goNext}
              aria-label="Next slide"
              data-testid="template-viewer-next"
              className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
