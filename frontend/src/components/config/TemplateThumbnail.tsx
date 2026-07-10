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

/**
 * CSP for the preview document: uploaded template HTML/CSS must not be able
 * to trigger ANY external network fetch from the frame (img/link tags, css
 * url()/@import — passive egress). The legit live render only needs inline
 * styles plus data:/blob: resources: the /source endpoint resolves
 * {{ds-asset:ID}} handles to data: URIs at serve time, and token CSS arrives
 * inline. sandbox="" on the iframe already blocks scripts/same-origin; this
 * closes the passive-fetch channel sandbox does not.
 */
const PREVIEW_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:;";

/**
 * A {{ds-asset:ID}} handle that still reaches the builder (a backend that
 * predates serve-time resolution, or an id its resolver could not satisfy)
 * would resolve as a relative URL inside the frame and be refused by the CSP
 * above — one failed-resource console error per occurrence, in every card.
 * Neutralize to the inert `data:,` placeholder (the import rewrite's own
 * convention for unresolvable refs): renders as nothing, never fetches.
 */
const DS_ASSET_HANDLE_RE = /\{\{ds-asset:\d+\}\}/g;

/**
 * Compose the preview document: the template layout with its token
 * stylesheet resolved and preview-only overflow clipping. Rendered ONLY in a
 * fully-sandboxed iframe.
 *
 * The wrapper is SYNTHESIZED — the CSP meta is the first fetch-capable byte
 * of the document, unconditionally. Injecting into a found <head> is not
 * enough: malformed-but-parser-preserved markup (e.g. an <img> BEFORE the
 * <html> tag) would declare resources ahead of the policy. DOMParser gives
 * browser-grade handling of malformed input without fetching or executing
 * anything; the parsed head content is re-emitted AFTER the guard block and
 * the parsed body (attributes included, via its own serialization) follows.
 */
function buildTemplatePreviewDoc(layoutHtml: string, tokenCss: string | null): string {
  const inlineLayout = layoutHtml.replace(DS_ASSET_HANDLE_RE, 'data:,');
  const inlineTokenCss = tokenCss ? tokenCss.replace(DS_ASSET_HANDLE_RE, 'data:,') : tokenCss;
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">`;
  const previewReset = '<style>html,body{margin:0;overflow:hidden}</style>';
  const guard = cspMeta + (inlineTokenCss ? `<style>${inlineTokenCss}</style>` : '') + previewReset;
  const parsed = new DOMParser().parseFromString(inlineLayout, 'text/html');
  const templateHead = parsed.head?.innerHTML ?? '';
  const templateBody = parsed.body?.outerHTML ?? '<body></body>';
  return `<!DOCTYPE html><html><head>${guard}${templateHead}</head>${templateBody}</html>`;
}

const FramePlaceholder: React.FC = () => (
  <span className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
    <Layers className="size-5" />
  </span>
);

/** The scaled/clipped live frame (SlideTile's fixed-frame pattern). */
const LiveTemplateFrame: React.FC<{ dsId: number; templateId: number; name: string }> = ({
  dsId,
  templateId,
  name,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);
  const [doc, setDoc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    configApi
      .getDesignSystemTemplateSource(dsId, templateId)
      .then((src) => {
        if (!cancelled) setDoc(buildTemplatePreviewDoc(src.layout_html, src.token_css));
      })
      .catch((err) => {
        console.error(`Failed to load template ${templateId} source for preview:`, err);
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [dsId, templateId]);

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
          aria-hidden="true"
          data-testid="template-live-preview"
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
