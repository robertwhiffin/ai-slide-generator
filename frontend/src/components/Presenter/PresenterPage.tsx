/**
 * The private presenter window at /sessions/:sessionId/present.
 *
 * It shows what the presenter says and what comes next, for the slide that
 * presentation mode reports. Presentation mode is the only source of truth:
 * Next and Back here only post `cmd` messages, and the shown slide changes only
 * when a `state` message arrives. Read-only in this release. The Notes panel
 * slides in from the right, like html-it's presenter notes drawer, and covers
 * only the "Up next" column; everything else stays where it is.
 * See docs/technical/presenter-view.md.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import type { Slide, SlideDeck } from '../../types/slide';
import { api } from '../../services/api';
import {
  buildSlideDocument,
  slideHostFrameStyle,
  SLIDE_FRAME_H,
  SLIDE_FRAME_W,
  SLIDE_ROOT_RESET_STYLE,
} from '../../services/slideDocument';
import {
  joinPresenterChannel,
  type PresenterCmd,
  type PresenterMessage,
} from '../../services/presenterChannel';

const HINT_TEXT = 'Share only the slides window. Full screen on one screen will cover this window.';
const HINT_KEY = 'tellr-presenter-hint-seen';
const MISMATCH_TEXT = 'Slides changed. Reopen the presentation to see them.';
/** The gap between the "On screen now" and "Up next" columns. */
const PREVIEW_GAP_PX = 24;
/** The Notes panel's left edge is Up next's: half the previews row plus half the gap. */
const NOTES_PANEL_LEFT = `calc(50% + ${PREVIEW_GAP_PX / 2}px)`;
/** Closed, the panel waits just past the right edge (as in html-it), so its shadow never shows. */
const NOTES_PANEL_CLOSED = 'translateX(102%)';

/** The first h1/h2 of the slide HTML, else "Slide N". */
function slideTitle(slide: Slide | undefined, index: number): string {
  if (slide?.html && typeof DOMParser !== 'undefined') {
    const doc = new DOMParser().parseFromString(slide.html, 'text/html');
    const text = doc.querySelector('h1, h2')?.textContent?.replace(/\s+/g, ' ').trim();
    if (text) return text;
  }
  return `Slide ${index + 1}`;
}

/** One paragraph per beat: beats are separated by a blank line. */
function beats(text: string | undefined): string[] {
  return (text ?? '')
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .filter(Boolean);
}

function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function readHintSeen(): boolean {
  try {
    return localStorage.getItem(HINT_KEY) !== null;
  } catch {
    return true;
  }
}

function previewDocument(deck: SlideDeck, slide: Slide): string {
  const extraHeadStyle = `
    html, body { width: 100%; height: 100%; margin: 0 !important; padding: 0 !important; overflow: hidden; }
    :where(html) { background: #ffffff; }
    canvas { max-width: 100%; height: auto; }
    .slide-container { margin: 0; }
    ${SLIDE_ROOT_RESET_STYLE}
    ${slideHostFrameStyle('.slide-container')}`;
  const slideScripts = slide.scripts || '';
  const scripts = slideScripts
    ? `
    (function () {
      var attempts = 0;
      function run() {
        try { ${slideScripts} } catch (err) { console.error('[Presenter] Chart initialization error:', err); }
      }
      function wait() {
        attempts++;
        if (typeof Chart !== 'undefined') run();
        else if (attempts < 50) setTimeout(wait, 100);
      }
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wait);
      else wait();
    })();`
    : '';
  return buildSlideDocument(`<div class="slide-container">${slide.html}</div>`, {
    css: deck.css,
    externalScripts: deck.external_scripts,
    scripts,
    extraHeadStyle,
  });
}

/**
 * A passive 16:9 preview: a 1280x720 sandboxed frame scaled to fit its area.
 *
 * The box is the largest 16:9 rectangle that fits both the area's width and
 * its height, sized in script as html-it's presenter does (CSS alone cannot
 * hold both limits), so the page never grows past the window.
 */
function SlidePreview({ deck, slide, title }: { deck: SlideDeck; slide: Slide; title: string }) {
  const areaRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  const srcDoc = useMemo(() => previewDocument(deck, slide), [deck, slide]);

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const measure = () => {
      const aw = area.clientWidth;
      const ah = area.clientHeight;
      if (aw <= 0 || ah <= 0) return;
      const w = Math.floor(Math.min(aw, (ah * SLIDE_FRAME_W) / SLIDE_FRAME_H));
      setBox({ w, h: Math.floor((w * SLIDE_FRAME_H) / SLIDE_FRAME_W) });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    return () => observer.disconnect();
  }, []);

  const scale = box ? box.w / SLIDE_FRAME_W : 0.4;

  return (
    <figure className="flex min-h-0 min-w-0 flex-col gap-2">
      <figcaption className="shrink-0 text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</figcaption>
      <div ref={areaRef} className="min-h-0 flex-1">
        <div
          className="relative overflow-hidden rounded-md bg-black ring-1 ring-slate-700"
          style={box ? { width: `${box.w}px`, height: `${box.h}px` } : { width: '100%', aspectRatio: '16 / 9' }}
        >
          <iframe
            title={title}
            srcDoc={srcDoc}
            sandbox="allow-scripts"
            tabIndex={-1}
            aria-hidden="true"
            style={{
              width: `${SLIDE_FRAME_W}px`,
              height: `${SLIDE_FRAME_H}px`,
              border: 'none',
              display: 'block',
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              pointerEvents: 'none',
            }}
          />
        </div>
      </div>
    </figure>
  );
}

export function PresenterPage() {
  const { sessionId = '' } = useParams<{ sessionId: string }>();

  const [deck, setDeck] = useState<SlideDeck | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  // What presentation mode last reported. Null until the first state message.
  const [reported, setReported] = useState<{ index: number; total: number; deckVersion: number | null } | null>(
    null,
  );
  const [notesOpen, setNotesOpen] = useState(false);
  const [hintVisible, setHintVisible] = useState(() => !readHintSeen());

  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  const channelRef = useRef<ReturnType<typeof joinPresenterChannel> | null>(null);
  const fetchedVersionRef = useRef<number | null | undefined>(undefined);
  const lastPostedVersionRef = useRef<number | null | undefined>(undefined);
  const fetchingRef = useRef(false);

  const load = useCallback(async () => {
    if (!sessionId) return;
    fetchingRef.current = true;
    try {
      const result = await api.getSlides(sessionId);
      fetchedVersionRef.current = result.slide_deck?.version ?? null;
      setDeck(result.slide_deck);
      setLoadError(false);
    } catch {
      setLoadError(true);
    } finally {
      fetchingRef.current = false;
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // The hint shows once: mark it seen as soon as it is shown.
  useEffect(() => {
    if (!hintVisible) return;
    try {
      localStorage.setItem(HINT_KEY, '1');
    } catch {
      // Storage is unavailable; the hint simply shows again next time.
    }
    // Only on first show.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Elapsed clock.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Channel: render only what presentation mode reports.
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (!sessionId) return;
    const onMessage = (m: PresenterMessage) => {
      if (m.type !== 'state') return;
      setReported({ index: m.index, total: m.total, deckVersion: m.deckVersion });

      // Refetch when the posted deck version changes and differs from the deck we hold.
      if (m.deckVersion !== lastPostedVersionRef.current) {
        lastPostedVersionRef.current = m.deckVersion;
        if (
          !fetchingRef.current &&
          fetchedVersionRef.current !== undefined &&
          fetchedVersionRef.current !== m.deckVersion
        ) {
          void loadRef.current();
        }
      }
    };
    channelRef.current = joinPresenterChannel(sessionId, onMessage);
    return () => {
      channelRef.current?.close();
      channelRef.current = null;
    };
  }, [sessionId]);

  const sendCmd = useCallback((action: PresenterCmd['action']) => {
    channelRef.current?.post({ type: 'cmd', action });
  }, []);

  // Keys in the presenter window.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case 'ArrowRight':
        case ' ':
        case 'PageDown':
          e.preventDefault();
          sendCmd('next');
          break;
        case 'ArrowLeft':
        case 'Backspace':
        case 'PageUp':
          e.preventDefault();
          sendCmd('prev');
          break;
        case 'n':
        case 'N':
          e.preventDefault();
          setNotesOpen((v) => !v);
          break;
        case 'Escape':
          setNotesOpen(false);
          break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sendCmd]);

  const slides = deck?.slides ?? [];
  const lastIndex = Math.max(slides.length - 1, 0);
  const index = Math.min(reported?.index ?? 0, lastIndex);
  const total = reported?.total ?? slides.length;
  const current = slides[index];
  const next = index < slides.length - 1 ? slides[index + 1] : undefined;
  const readAloud = beats(current?.talk_track);
  const comingUp = next ? beats(next.talk_track)[0] : undefined;
  const notes = beats(current?.speaker_notes);
  const deckMismatch =
    deck !== null && reported !== null && (deck.version ?? null) !== reported.deckVersion;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-900 text-slate-100">
      {/* Everything above the bottom bar. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {hintVisible && (
          <div className="flex items-center justify-between gap-4 bg-amber-100 px-6 py-2 text-sm text-amber-900">
            <span>{HINT_TEXT}</span>
            <button
              type="button"
              onClick={() => setHintVisible(false)}
              className="rounded px-2 py-1 font-medium hover:bg-amber-200"
            >
              Got it
            </button>
          </div>
        )}

        {loading && !deck ? (
          <div className="flex flex-1 items-center justify-center text-slate-400">Loading slides…</div>
        ) : loadError && !deck ? (
          <div className="flex flex-1 items-center justify-center text-slate-300">
            Could not load the slides. Reopen the presenter view to try again.
          </div>
        ) : !current ? (
          <div className="flex flex-1 items-center justify-center text-slate-300">This deck has no slides yet.</div>
        ) : (
          <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden px-8 py-5">
            <header className="flex shrink-0 items-baseline gap-4 border-b border-slate-700 pb-3">
              <span className="whitespace-nowrap text-sm font-semibold text-slate-400">
                Slide {index + 1} of {total}
              </span>
              <h1 className="min-w-0 flex-1 truncate text-xl font-semibold">{slideTitle(current, index)}</h1>
              <span className="font-mono text-xl tabular-nums text-slate-300" aria-label="Elapsed time">
                {formatClock(now - startedAt)}
              </span>
            </header>

            {deckMismatch && (
              <p className="shrink-0 rounded-md bg-amber-900/60 px-4 py-2 text-sm text-amber-100">{MISMATCH_TEXT}</p>
            )}

            {/* A long talk track scrolls inside this section, so the previews keep their room. */}
            <section className="flex min-h-0 flex-col gap-3 overflow-y-auto" style={{ flex: '0 1 auto' }}>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Read aloud</h2>
              {readAloud.length > 0 ? (
                <div className="flex flex-col gap-3" style={{ fontSize: '24px', lineHeight: 1.45 }}>
                  {readAloud.map((beat, i) => (
                    <p key={i} className="whitespace-pre-wrap">
                      {beat}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="text-lg text-slate-400">No talk track for this slide.</p>
              )}
            </section>

            <section className="flex shrink-0 flex-col gap-1 rounded-md bg-slate-800 px-4 py-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Coming up</h2>
              {next ? (
                <>
                  <p className="font-semibold">{slideTitle(next, index + 1)}</p>
                  {comingUp && <p className="whitespace-pre-wrap text-slate-300">{comingUp}</p>}
                </>
              ) : (
                <p className="font-semibold">End of deck</p>
              )}
            </section>

            {/* The previews take what is left, never less than 40% of the page (html-it's rule). The Notes
                panel is positioned against this row, over the Up next column, and moves nothing. */}
            <div
              className="grid min-h-0 grid-cols-2"
              style={{
                position: 'relative',
                flex: '1 0 40%',
                gridTemplateRows: 'minmax(0, 1fr)',
                gap: `${PREVIEW_GAP_PX}px`,
              }}
            >
              {deck && <SlidePreview deck={deck} slide={current} title="On screen now" />}
              {deck && next && <SlidePreview deck={deck} slide={next} title="Up next" />}
              <aside
                data-testid="presenter-notes-drawer"
                aria-label="Notes"
                aria-hidden={notesOpen ? undefined : true}
                className="overflow-y-auto rounded-md border border-slate-700 bg-slate-800 px-7 py-6 text-slate-100 shadow-[-12px_0_40px_rgba(0,0,0,0.35)] transition-[transform,visibility] duration-[280ms] ease-out motion-reduce:transition-none"
                style={{
                  position: 'absolute',
                  top: 0,
                  right: 0,
                  bottom: 0,
                  left: NOTES_PANEL_LEFT,
                  zIndex: 5,
                  transform: notesOpen ? 'none' : NOTES_PANEL_CLOSED,
                  visibility: notesOpen ? 'visible' : 'hidden',
                }}
              >
                <div className="mb-3 text-[10px] font-semibold uppercase leading-none tracking-[0.12em] text-slate-400">
                  Notes · this slide
                </div>
                <h2 className="mb-3 text-lg font-semibold text-white">Notes</h2>
                {notes.length > 0 ? (
                  <div className="flex flex-col gap-2.5 text-base leading-relaxed">
                    {notes.map((para, i) => (
                      <p key={i} className="whitespace-pre-wrap">
                        {para}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className="text-slate-400">No speaker notes for this slide.</p>
                )}
              </aside>
            </div>
          </main>
        )}
      </div>

      <footer className="flex items-center gap-3 border-t border-slate-700 px-8 py-3 text-sm">
        <button
          type="button"
          onClick={() => sendCmd('prev')}
          className="rounded-md bg-slate-700 px-4 py-2 font-medium hover:bg-slate-600"
        >
          Back
        </button>
        <button
          type="button"
          onClick={() => sendCmd('next')}
          className="rounded-md bg-slate-700 px-4 py-2 font-medium hover:bg-slate-600"
        >
          Next
        </button>
        <button
          type="button"
          onClick={() => setNotesOpen((v) => !v)}
          aria-label="Show notes"
          aria-pressed={notesOpen}
          className={`rounded-md px-4 py-2 font-medium hover:bg-slate-600 ${notesOpen ? 'bg-slate-500' : 'bg-slate-700'}`}
        >
          Notes
        </button>
        <span className="text-slate-400">← → move · N notes</span>
      </footer>
    </div>
  );
}
