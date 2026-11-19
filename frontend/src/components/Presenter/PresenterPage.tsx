/**
 * The private presenter window at /sessions/:sessionId/present.
 *
 * It shows what the presenter says and what comes next, for the slide that
 * presentation mode reports. Presentation mode is the only source of truth:
 * Next and Back here only post `cmd` messages, and the shown slide changes only
 * when a `state` message arrives. Read-only in this release. See
 * docs/technical/presenter-view.md.
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
  LINK_TIMEOUT_MS,
  type PresenterCmd,
  type PresenterMessage,
} from '../../services/presenterChannel';

const HINT_TEXT = 'Share only the slides window. Full screen on one screen will cover this window.';
const HINT_KEY = 'tellr-presenter-hint-seen';
const MISMATCH_TEXT = 'Slides changed. Reopen the presentation to see them.';

type Permission = 'CAN_VIEW' | 'CAN_EDIT' | 'CAN_MANAGE';

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

/** A passive 16:9 preview: a 1280x720 sandboxed frame scaled to fit its box. */
function SlidePreview({ deck, slide, title }: { deck: SlideDeck; slide: Slide; title: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.4);
  const srcDoc = useMemo(() => previewDocument(deck, slide), [deck, slide]);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = () => {
      if (box.clientWidth > 0) setScale(box.clientWidth / SLIDE_FRAME_W);
    };
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, []);

  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</figcaption>
      <div
        ref={boxRef}
        className="relative w-full overflow-hidden rounded-md bg-black ring-1 ring-slate-700"
        style={{ aspectRatio: '16 / 9' }}
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
    </figure>
  );
}

export function PresenterPage() {
  const { sessionId = '' } = useParams<{ sessionId: string }>();

  const [deck, setDeck] = useState<SlideDeck | null>(null);
  const [permission, setPermission] = useState<Permission | undefined>(undefined);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  // What presentation mode last reported. Null until the first state message.
  const [reported, setReported] = useState<{ index: number; total: number; deckVersion: number | null } | null>(
    null,
  );
  const [linked, setLinked] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [hintVisible, setHintVisible] = useState(() => !readHintSeen());

  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  const channelRef = useRef<ReturnType<typeof joinPresenterChannel> | null>(null);
  const linkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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
      setPermission(result.my_permission);
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
      setLinked(true);
      if (linkTimerRef.current) clearTimeout(linkTimerRef.current);
      linkTimerRef.current = setTimeout(() => setLinked(false), LINK_TIMEOUT_MS);

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
      if (linkTimerRef.current) clearTimeout(linkTimerRef.current);
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

  const openPresentation = () => {
    const opener = window.opener as Window | null;
    if (opener && !opener.closed) {
      opener.focus();
      return;
    }
    // A new tab, never this one: the presenter stays open.
    const page = permission === 'CAN_VIEW' ? 'view' : 'edit';
    window.open(`/sessions/${sessionId}/${page}`, '_blank');
  };

  const slides = deck?.slides ?? [];
  const lastIndex = Math.max(slides.length - 1, 0);
  const index = Math.min(reported?.index ?? 0, lastIndex);
  const total = reported?.total ?? slides.length;
  const current = slides[index];
  const next = index < slides.length - 1 ? slides[index + 1] : undefined;
  const readAloud = beats(current?.talk_track);
  const comingUp = next ? beats(next.talk_track)[0] : undefined;
  const notes = (current?.speaker_notes ?? '').trim();
  const deckMismatch =
    deck !== null && reported !== null && (deck.version ?? null) !== reported.deckVersion;

  return (
    <div className="flex h-screen flex-col bg-slate-900 text-slate-100">
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
        <main className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-5">
          <header className="flex items-baseline gap-4 border-b border-slate-700 pb-3">
            <span className="whitespace-nowrap text-sm font-semibold text-slate-400">
              Slide {index + 1} of {total}
            </span>
            <h1 className="min-w-0 flex-1 truncate text-xl font-semibold">{slideTitle(current, index)}</h1>
            <span className="font-mono text-xl tabular-nums text-slate-300" aria-label="Elapsed time">
              {formatClock(now - startedAt)}
            </span>
          </header>

          {deckMismatch && (
            <p className="rounded-md bg-amber-900/60 px-4 py-2 text-sm text-amber-100">{MISMATCH_TEXT}</p>
          )}

          <section className="flex flex-col gap-3">
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

          <section className="flex flex-col gap-1 rounded-md bg-slate-800 px-4 py-3">
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

          <div className="grid grid-cols-2 gap-6">
            {deck && <SlidePreview deck={deck} slide={current} title="On screen now" />}
            {deck && next && <SlidePreview deck={deck} slide={next} title="Up next" />}
          </div>

          {notesOpen && (
            <section
              data-testid="presenter-notes-drawer"
              className="flex flex-col gap-2 rounded-md border border-slate-600 bg-slate-800 px-4 py-3"
            >
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Notes</h2>
              {notes ? (
                <p className="whitespace-pre-wrap text-base">{notes}</p>
              ) : (
                <p className="text-slate-400">No speaker notes for this slide.</p>
              )}
            </section>
          )}
        </main>
      )}

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
        <span className="ml-auto flex items-center gap-3">
          <span className={linked ? 'text-emerald-400' : 'text-slate-400'}>
            {linked ? 'Slides: linked' : 'Slides: not linked'}
          </span>
          {!linked && (
            <button
              type="button"
              onClick={openPresentation}
              className="rounded-md bg-slate-700 px-3 py-2 font-medium hover:bg-slate-600"
            >
              Open presentation
            </button>
          )}
        </span>
      </footer>
    </div>
  );
}
