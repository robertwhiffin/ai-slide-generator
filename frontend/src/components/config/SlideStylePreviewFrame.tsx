/**
 * Visual preview for a slide style.
 *
 * A slide style is prose the model interprets, not deterministic CSS, so the
 * only faithful "what will my slides look like" preview is a model-generated
 * sample deck. The backend generates/caches that deck in a background job; this
 * component READS it (never triggers generation directly) and renders it.
 *
 * SECURITY: the sample HTML/CSS is MODEL OUTPUT and is treated as hostile. It is
 * rendered exactly like uploaded template previews — a fully-sandboxed iframe
 * (`sandbox=""`: no scripts, no same-origin) whose srcDoc carries the strict,
 * network-blocked slide CSP (see slideDocument.ts). Scripts were already
 * stripped server-side; the empty sandbox is the real guarantee they never run.
 */

import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Eye, Loader2, RefreshCw, X } from 'lucide-react';
import { configApi } from '../../api/config';
import type { SlideStylePreview, SlideStylePreviewStatus } from '../../api/config';
import {
  buildSlideDocument,
  SLIDE_FRAME_H,
  SLIDE_FRAME_W,
  SLIDE_PREVIEW_RESET_STYLE,
} from '../../services/slideDocument';
import { LazyMount } from './TemplateThumbnail';

// ---------------------------------------------------------------------------
// Query cache + polling hook
// ---------------------------------------------------------------------------
// Cache the latest response per style so re-selecting a style shows its preview
// instantly instead of re-fetching. Keyed by styleId; the value carries the
// fingerprint so a stale entry is visibly marked while a refresh runs.
const previewCache = new Map<number, SlideStylePreview>();

const POLL_START_MS = 1000;
// Cap the backoff low so a finished generation surfaces promptly (a completed
// deck is otherwise invisible until the next poll fires).
const POLL_MAX_MS = 3000;
// Statuses that mean "a fresh result may still arrive" — keep polling.
const POLLING_STATUSES: SlideStylePreviewStatus[] = ['queued', 'generating', 'stale'];

interface UseSlideStylePreviewResult {
  preview: SlideStylePreview | null;
  loading: boolean;
  error: string | null;
  regenerate: () => void;
}

/**
 * Fetch (and, while in flight, poll) the cached preview for a style.
 *
 * - Never fetches when `enabled` is false or `styleId` is null.
 * - Cancels the in-flight request and stops polling when the style changes or
 *   the component unmounts (AbortController) — so rapid selection changes in the
 *   picker never fan out or race.
 * - Backs off polling while the preview is queued/generating/stale.
 */
export function useSlideStylePreview(
  styleId: number | null,
  enabled: boolean,
): UseSlideStylePreviewResult {
  const [preview, setPreview] = useState<SlideStylePreview | null>(
    styleId != null ? previewCache.get(styleId) ?? null : null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped by regenerate() to force a fresh poll cycle.
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (styleId == null || !enabled) {
      return;
    }
    // Show the cached copy immediately (may be stale; polling will refresh it).
    setPreview(previewCache.get(styleId) ?? null);
    setError(null);

    let cancelled = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = POLL_START_MS;

    const poll = async () => {
      setLoading(true);
      try {
        const res = await configApi.getSlideStylePreview(styleId, controller.signal);
        if (cancelled) return;
        previewCache.set(styleId, res);
        setPreview(res);
        setError(null);
        if (POLLING_STATUSES.includes(res.status)) {
          delay = Math.min(delay * 1.5, POLL_MAX_MS);
          timer = setTimeout(poll, delay);
        }
      } catch (e) {
        if (cancelled || controller.signal.aborted) return;
        // A fetch error must never break the picker; surface it non-blockingly.
        setError(e instanceof Error ? e.message : 'Failed to load preview');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    poll();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [styleId, enabled, nonce]);

  const regenerate = useCallback(() => {
    if (styleId == null) return;
    // Fire-and-forget the admin regenerate, then restart polling.
    configApi
      .regenerateSlideStylePreview(styleId)
      .catch(() => {
        /* surfaced via the next poll's status; ignore here */
      })
      .finally(() => setNonce((n) => n + 1));
  }, [styleId]);

  return { preview, loading, error, regenerate };
}

// ---------------------------------------------------------------------------
// Single scaled slide frame (sandboxed)
// ---------------------------------------------------------------------------
/** Render one preview slide into a scaled, clipped, fully-sandboxed iframe. */
const SlideFrame: React.FC<{
  slideHtml: string;
  css: string;
  name: string;
  /** Set on the modal (content the user reads) to expose it to assistive tech. */
  exposeToA11y?: boolean;
  testId?: string;
}> = ({ slideHtml, css, name, exposeToA11y, testId }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);

  const doc = React.useMemo(
    () =>
      buildSlideDocument(slideHtml, {
        css,
        extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE,
      }),
    [slideHtml, css],
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      // A zero measurement is transient (pre-layout / display:none ancestor);
      // keep the last good scale rather than tearing the iframe down.
      if (!el.offsetWidth) return;
      setScale(el.offsetWidth / SLIDE_FRAME_W);
    };
    update();
    const observer =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null;
    observer?.observe(el);
    window.addEventListener('resize', update);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', update);
    };
  }, []);

  return (
    <div ref={containerRef} className="absolute inset-0 overflow-hidden">
      {scale === 0 ? null : (
        <iframe
          srcDoc={doc}
          title={`${name} style preview`}
          sandbox=""
          scrolling="no"
          tabIndex={-1}
          aria-hidden={exposeToA11y ? undefined : true}
          data-testid={testId}
          className="border-0"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: `${SLIDE_FRAME_W}px`,
            height: `${SLIDE_FRAME_H}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
            pointerEvents: 'none',
          }}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Status overlay helpers
// ---------------------------------------------------------------------------
const StatusOverlay: React.FC<{ children: React.ReactNode; tone?: 'info' | 'error' }> = ({
  children,
  tone = 'info',
}) => (
  <div
    className={`absolute inset-0 flex flex-col items-center justify-center gap-1 p-2 text-center text-xs ${
      tone === 'error' ? 'text-destructive' : 'text-muted-foreground'
    } bg-background/70`}
  >
    {children}
  </div>
);

function hasRenderableSlides(preview: SlideStylePreview | null): boolean {
  return !!preview && Array.isArray(preview.slides) && preview.slides.length > 0;
}

// ---------------------------------------------------------------------------
// Mini-deck modal
// ---------------------------------------------------------------------------
const SlideStylePreviewModal: React.FC<{
  name: string;
  preview: SlideStylePreview;
  onClose: () => void;
}> = ({ name, preview, onClose }) => {
  const slides = preview.slides ?? [];
  const pageCount = Math.max(1, slides.length);
  const [index, setIndex] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);

  const goPrev = useCallback(
    () => setIndex((i) => (i - 1 + pageCount) % pageCount),
    [pageCount],
  );
  const goNext = useCallback(() => setIndex((i) => (i + 1) % pageCount), [pageCount]);

  useEffect(() => {
    // Focus the close button on open (focus trap entry) and restore on unmount.
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      else if (event.key === 'ArrowLeft') goPrev();
      else if (event.key === 'ArrowRight') goNext();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [onClose, goPrev, goNext]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`${name} style preview`}
      data-testid="slide-style-preview-modal"
    >
      <div className="absolute inset-0 bg-black/60" onClick={onClose} data-testid="slide-style-preview-backdrop" />
      <div className="relative flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-border bg-background shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-medium text-foreground">{name}</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Sample deck generated from this style{preview.stale ? ' (refreshing…)' : ''}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close style preview"
            data-testid="slide-style-preview-close"
            className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="relative aspect-video w-full overflow-hidden bg-muted/30">
          <SlideFrame
            slideHtml={slides[index] ?? ''}
            css={preview.css ?? ''}
            name={name}
            exposeToA11y
            testId="slide-style-preview-modal-frame"
          />
        </div>

        {pageCount > 1 && (
          <div className="flex items-center justify-center gap-3 border-t border-border px-4 py-2">
            <button
              type="button"
              onClick={goPrev}
              aria-label="Previous slide"
              data-testid="slide-style-preview-prev"
              className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ChevronLeft className="size-4" />
            </button>
            <span className="text-xs text-muted-foreground" data-testid="slide-style-preview-counter">
              Slide {index + 1} of {pageCount}
            </span>
            <button
              type="button"
              onClick={goNext}
              aria-label="Next slide"
              data-testid="slide-style-preview-next"
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

// ---------------------------------------------------------------------------
// Public: preview thumbnail + opener
// ---------------------------------------------------------------------------
/**
 * Hero-slide thumbnail for a slide style, with an accessible opener to the
 * mini-deck modal. Renders EVERY status state non-blockingly: a fetch error or
 * an in-flight generation never blocks selecting or generating with the style.
 */
export const SlideStylePreviewThumbnail: React.FC<{
  styleId: number;
  name: string;
  /** Gate fetching (e.g. only for the settled selection / on-screen cards). */
  enabled?: boolean;
  className?: string;
  /** Show a regenerate control (admins). */
  canRegenerate?: boolean;
}> = ({ styleId, name, enabled = true, className, canRegenerate }) => {
  const { preview, loading, error, regenerate } = useSlideStylePreview(styleId, enabled);
  const [modalOpen, setModalOpen] = useState(false);

  const status = preview?.status ?? (loading ? 'queued' : 'missing');
  const renderable = hasRenderableSlides(preview);
  const hero = renderable && preview ? preview.slides![0] : null;

  const overlay = (() => {
    if (renderable && preview) {
      // A usable copy exists. Only overlay a small "refreshing" hint if stale.
      if (preview.stale || status === 'generating' || status === 'queued') {
        return (
          <div className="absolute right-1 top-1 flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" /> updating
          </div>
        );
      }
      return null;
    }
    if (error) {
      return (
        <StatusOverlay tone="error">
          <AlertTriangle className="size-4" />
          <span>Preview unavailable</span>
        </StatusOverlay>
      );
    }
    if (status === 'failed') {
      return (
        <StatusOverlay tone="error">
          <AlertTriangle className="size-4" />
          <span>Preview failed{preview?.error_code ? ` (${preview.error_code})` : ''}</span>
        </StatusOverlay>
      );
    }
    if (status === 'queued' || status === 'generating') {
      return (
        <StatusOverlay>
          <Loader2 className="size-4 animate-spin" />
          <span>Generating preview…</span>
        </StatusOverlay>
      );
    }
    return (
      <StatusOverlay>
        <Eye className="size-4" />
        <span>Preview will generate on selection</span>
      </StatusOverlay>
    );
  })();

  return (
    <div className={className} data-testid="slide-style-preview" data-preview-status={status}>
      <div className="relative aspect-video w-full overflow-hidden rounded-md border border-border bg-muted/30">
        {hero != null && (
          <SlideFrame slideHtml={hero} css={preview?.css ?? ''} name={name} />
        )}
        {overlay}
        {/* A real button opener — keyboard reachable, labeled. Only clickable
            when there is a renderable deck to open. */}
        {renderable && (
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            aria-label={`Preview slide style: ${name}`}
            data-testid="slide-style-preview-open"
            className="absolute inset-0 cursor-zoom-in bg-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        )}
      </div>

      {(canRegenerate || error || status === 'failed') && (
        <div className="mt-1 flex items-center justify-end">
          {canRegenerate && (
            <button
              type="button"
              onClick={regenerate}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              data-testid="slide-style-preview-regenerate"
            >
              <RefreshCw className="size-3" /> Regenerate
            </button>
          )}
        </div>
      )}

      {modalOpen && renderable && preview && (
        <SlideStylePreviewModal
          name={name}
          preview={preview}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  );
};

/**
 * List/card wrapper: lazily mounts the thumbnail so a library of many styles
 * does not fan out a preview fetch for every card at initial render.
 */
export const LazySlideStylePreview: React.FC<{
  styleId: number;
  name: string;
  canRegenerate?: boolean;
  className?: string;
}> = ({ styleId, name, canRegenerate, className }) => (
  <LazyMount className={className} rootMargin="0px">
    <SlideStylePreviewThumbnail
      styleId={styleId}
      name={name}
      enabled
      canRegenerate={canRegenerate}
    />
  </LazyMount>
);
