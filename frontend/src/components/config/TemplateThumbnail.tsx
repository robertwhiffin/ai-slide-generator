/**
 * Template preview thumbnail with a live-render fallback.
 *
 * Synthetic bundles can ship a preview screenshot (served via the template
 * thumbnail endpoint) — that stays the preferred source. Real Claude Design
 * exports ship NO screenshots (their preview/ files are HTML demo pages), so
 * when `thumbnail_url` is null the stored template layout is fetched as JSON
 * and rendered as a scaled, clipped mini-card: a fixed 1280x720 frame inside
 * a fully-sandboxed iframe (`sandbox=""` — no scripts, no same-origin),
 * scaled with the same transform/clip machinery the slide tiles use.
 *
 * Everything is lazy: the frame mounts — and the megabyte source fetch fires —
 * only once the card is actually on screen, and the payload is then shared with
 * the expanded viewer rather than downloaded twice.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Layers } from 'lucide-react';
import { configApi, resolveApiUrl } from '../../api/config';
import type { DesignSystemTemplate } from '../../api/config';
// The hardened preview-document builder (CSP + inert parse) lives in its own
// module so the thumbnail and the expanded viewer share ONE renderer.
import {
  buildTemplatePreviewDoc,
  countTemplateSlides,
  PREVIEW_STAGE_H,
  PREVIEW_STAGE_W,
} from './templatePreviewDoc';

type TemplateSource = { layout_html: string; token_css: string | null };

/**
 * In-flight/settled `/source` responses, shared by the card and the expanded
 * viewer. A template's source is MEGABYTES (its brand assets and webfonts are
 * inlined as data: URIs at serve time), and the card and the modal render the
 * same template from the same payload — without this, opening the viewer
 * re-downloads everything the card already had.
 *
 * Bounded because the entries are that large: keep only the few most recently
 * used templates and let the rest be collected.
 */
const MAX_CACHED_SOURCES = 4;
const sourceCache = new Map<string, Promise<TemplateSource>>();

function fetchTemplateSource(dsId: number, templateId: number): Promise<TemplateSource> {
  const key = `${dsId}:${templateId}`;
  const cached = sourceCache.get(key);
  if (cached) {
    // Refresh recency: re-inserting moves the key to the end of the Map order.
    sourceCache.delete(key);
    sourceCache.set(key, cached);
    return cached;
  }
  const pending = configApi
    .getDesignSystemTemplateSource(dsId, templateId)
    .then((src) => ({ layout_html: src.layout_html, token_css: src.token_css }))
    .catch((err) => {
      // A failed fetch must not be cached as a permanent failure.
      sourceCache.delete(key);
      throw err;
    });
  sourceCache.set(key, pending);
  if (sourceCache.size > MAX_CACHED_SOURCES) {
    const oldest = sourceCache.keys().next();
    if (!oldest.done) sourceCache.delete(oldest.value);
  }
  return pending;
}

/**
 * Defer mounting children until the placeholder scrolls near the viewport
 * (IntersectionObserver) — the Claude Design detail view's per-card pattern.
 *
 * `rootMargin` defaults to a 200px prefetch, which is right for cheap children
 * (a 36px asset thumbnail): mount just before they scroll in, so they are never
 * seen loading. Children whose mount costs MEGABYTES pass '0px' instead and
 * trade that head start for not paying at all until they are really on screen.
 */
export const LazyMount: React.FC<{
  className?: string;
  children: React.ReactNode;
  rootMargin?: string;
}> = ({ className, children, rootMargin = '200px' }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || visible) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [visible, rootMargin]);
  return (
    <div ref={ref} className={className}>
      {visible ? children : null}
    </div>
  );
};

const FramePlaceholder: React.FC = () => (
  <span className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
    <Layers className="size-5" />
  </span>
);

/**
 * The scaled/clipped live frame (SlideTile's fixed-frame pattern).
 *
 * `slideIndex` renders just one of a multi-slide template's sections — the
 * viewer's pagination. Exported so the expanded viewer reuses THIS frame
 * (sandbox="" + the no-egress CSP + data:-resolved assets) rather than
 * standing up a second, weaker renderer.
 */
export const LiveTemplateFrame: React.FC<{
  dsId: number;
  templateId: number;
  name: string;
  slideIndex?: number;
  onSlideCount?: (count: number) => void;
  /** Set by the expanded viewer; also opts the frame into the a11y tree. */
  testId?: string;
}> = ({ dsId, templateId, name, slideIndex, onSlideCount, testId }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);
  const [doc, setDoc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [source, setSource] = useState<TemplateSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTemplateSource(dsId, templateId)
      .then((src) => {
        if (!cancelled) setSource(src);
      })
      .catch((err) => {
        console.error(`Failed to load template ${templateId} source for preview:`, err);
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [dsId, templateId]);

  // Report the section count once per fetched source so the viewer can build
  // its pager without parsing the layout a second time.
  useEffect(() => {
    if (source && onSlideCount) onSlideCount(countTemplateSlides(source.layout_html));
  }, [source, onSlideCount]);

  useEffect(() => {
    if (!source) return;
    setDoc(buildTemplatePreviewDoc(source.layout_html, source.token_css, slideIndex));
  }, [source, slideIndex]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const updateScale = () => setScale(el.offsetWidth / PREVIEW_STAGE_W);
    updateScale();
    const observer =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(updateScale) : null;
    observer?.observe(el);
    window.addEventListener('resize', updateScale);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', updateScale);
    };
  }, []);

  return (
    <div ref={containerRef} className="absolute inset-0 overflow-hidden">
      {failed || !doc || scale === 0 ? (
        <FramePlaceholder />
      ) : (
        <iframe
          srcDoc={doc}
          title={`${name} preview`}
          sandbox=""
          scrolling="no"
          tabIndex={-1}
          // A thumbnail is decorative (the card names the template); the
          // expanded viewer is the content the user came to read, so it is
          // exposed to assistive tech. The SANDBOX and CSP are identical in
          // both cases — only the a11y framing differs.
          aria-hidden={testId === undefined ? true : undefined}
          data-testid={testId ?? 'template-live-preview'}
          className="border-0"
          style={{
            width: `${PREVIEW_STAGE_W}px`,
            height: `${PREVIEW_STAGE_H}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
            pointerEvents: 'none',
          }}
        />
      )}
    </div>
  );
};

/**
 * One template card's preview area. Prefers the bundle-shipped screenshot;
 * live-renders the stored layout otherwise. `className` carries the caller's
 * dimensions/border styling (e.g. `aspect-video w-full` cards, `h-10 w-16`
 * file-browser rows).
 */
export const TemplateThumbnail: React.FC<{
  dsId: number;
  template: DesignSystemTemplate;
  className?: string;
}> = ({ dsId, template, className }) => {
  if (template.thumbnail_url) {
    return (
      <img
        src={resolveApiUrl(template.thumbnail_url)}
        alt={`${template.name} preview`}
        className={`${className ?? ''} object-cover`}
        onError={(e) => {
          (e.currentTarget as HTMLImageElement).style.visibility = 'hidden';
        }}
      />
    );
  }
  return (
    <LazyMount className={`${className ?? ''} relative overflow-hidden`} rootMargin="0px">
      {/* A card previews the template's FIRST slide. Passing the index also
          drops every other section from the built document, so a card does not
          parse (or paint) the eight slides it will never show — and, because
          template slides are `position:absolute; inset:0`, they would otherwise
          all stack and the card would show the LAST slide, not the first. */}
      <LiveTemplateFrame
        dsId={dsId}
        templateId={template.id}
        name={template.name}
        slideIndex={0}
      />
    </LazyMount>
  );
};
