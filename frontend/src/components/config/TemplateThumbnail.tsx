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
 * Everything is lazy: the frame mounts (and the source fetch fires) only
 * when the card scrolls near the viewport.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Layers } from 'lucide-react';
import { configApi, resolveApiUrl } from '../../api/config';
import type { DesignSystemTemplate } from '../../api/config';
// The hardened preview-document builder (CSP + inert parse) lives in its own
// module so the thumbnail and the expanded viewer share ONE renderer.
import { buildTemplatePreviewDoc, countTemplateSlides } from './templatePreviewDoc';

const TEMPLATE_W = 1280;
const TEMPLATE_H = 720;

/**
 * Defer mounting children until the placeholder scrolls near the viewport
 * (IntersectionObserver, 200px rootMargin) — the Claude Design detail view's
 * per-card pattern.
 */
export const LazyMount: React.FC<{ className?: string; children: React.ReactNode }> = ({
  className,
  children,
}) => {
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
      { rootMargin: '200px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [visible]);
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
  const [source, setSource] = useState<{ layout_html: string; token_css: string | null } | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    configApi
      .getDesignSystemTemplateSource(dsId, templateId)
      .then((src) => {
        if (!cancelled) setSource({ layout_html: src.layout_html, token_css: src.token_css });
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
    const updateScale = () => setScale(el.offsetWidth / TEMPLATE_W);
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
            width: `${TEMPLATE_W}px`,
            height: `${TEMPLATE_H}px`,
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
    <LazyMount className={`${className ?? ''} relative overflow-hidden`}>
      <LiveTemplateFrame dsId={dsId} templateId={template.id} name={template.name} />
    </LazyMount>
  );
};
