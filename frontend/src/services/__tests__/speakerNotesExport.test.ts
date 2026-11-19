/**
 * Speaker notes, Task 8 (plan D6, D7; PLAN-CORRECTIONS C0.4): notes reach both client-built exports.
 *
 *   - The records fallback (`buildCompositeHtml`) embeds one notes string per slide, in deck order, as
 *     `<script id="speaker-notes" type="application/json">`. Every `<` in that JSON is escaped as
 *     `<`, so a `</script>` typed into notes cannot close the element and inject markup.
 *   - The screenshot export (`exportPptxEditable(deck, sid, 'screenshot')`) posts `notes`, one entry per
 *     slide, aligned with `images` ('' for a slide with no notes).
 *
 * SABOTAGE (each run against a throwaway implementation, then reverted):
 *   - read only `notes`, never `speaker_notes`, or reverse the order  -> "in order" RED.
 *   - drop the `.replace(/</g, '\\u003c')` on the JSON                 -> "</script>" RED.
 *   - omit `notes` from the from-images body                           -> "screenshot" RED.
 *
 * Presenter plan Task 3: the notes pane holds the talk track, then a line `Notes:`, then the notes, built
 * by `presenterPaneText` (`../presenterText`). With one field empty, only the other is written, with no
 * heading. Both client-built exports use it. `presenterText` is loaded dynamically so the older cases still
 * run (and report) while the module does not exist yet.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SlideDeck } from '../../types/slide';
import { buildCompositeHtml } from '../domWalker';
import { api } from '../api';

vi.mock('../screenshotCapture', () => ({
  captureDeckAsPngDataUrls: vi.fn(async () => [
    'data:image/png;base64,AA==',
    'data:image/png;base64,AA==',
  ]),
}));

type FetchArgs = [RequestInfo | URL, RequestInit | undefined];

function stubFetch(response: Response) {
  const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>(async () => response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function deckWithNotes(notes: string[]): SlideDeck {
  return {
    title: 'Deck',
    slide_count: notes.length,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: notes.map((n, i) => ({
      index: i,
      slide_id: `s${i}`,
      html: `<div class="slide">Slide ${i}</div>`,
      scripts: '',
      speaker_notes: n,
    })),
  } as unknown as SlideDeck;
}

type PaneFields = { talk_track?: string; speaker_notes?: string; notes?: string };

function deckWithFields(fields: PaneFields[]): SlideDeck {
  return {
    title: 'Deck',
    slide_count: fields.length,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: fields.map((f, i) => ({
      index: i,
      slide_id: `s${i}`,
      html: `<div class="slide">Slide ${i}</div>`,
      scripts: '',
      ...f,
    })),
  } as unknown as SlideDeck;
}

// Both fields, talk track only, notes only.
const TWO_FIELD_SLIDES: PaneFields[] = [
  { talk_track: 'Say A.', speaker_notes: 'Know A.' },
  { talk_track: 'Say B.', speaker_notes: '' },
  { speaker_notes: 'Know C.' },
];
const TWO_FIELD_PANES = ['Say A.\n\nNotes:\nKnow A.', 'Say B.', 'Know C.'];

async function loadPresenterPaneText(): Promise<(slide: PaneFields) => string> {
  const path = '../presenterText';
  const mod = (await import(/* @vite-ignore */ path)) as {
    presenterPaneText: (slide: PaneFields) => string;
  };
  return mod.presenterPaneText;
}

function parse(html: string): Document {
  return new DOMParser().parseFromString(html, 'text/html');
}

function embeddedNotes(doc: Document): unknown {
  const el = doc.getElementById('speaker-notes');
  expect(el).not.toBeNull();
  return JSON.parse(el!.textContent!);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('speaker notes in the client-built exports', () => {
  // Sabotage target: read only the older `notes` key, or emit the notes out of deck order.
  it("buildCompositeHtml embeds each slide's notes in order", () => {
    const doc = parse(buildCompositeHtml(deckWithNotes(['Say A.', ''])));
    expect(embeddedNotes(doc)).toEqual(['Say A.', '']);
  });

  // Sabotage target: `s.speaker_notes || legacy` (an empty, cleared note falling back to a stale `notes` key).
  it('a cleared speaker_notes string wins over an older notes key', () => {
    const deck = deckWithNotes(['', '']);
    (deck.slides[0] as unknown as { notes: string }).notes = 'Old.';
    delete (deck.slides[1] as unknown as { speaker_notes?: string }).speaker_notes;
    (deck.slides[1] as unknown as { notes: string }).notes = 'Legacy B.';
    expect(embeddedNotes(parse(buildCompositeHtml(deck)))).toEqual(['', 'Legacy B.']);
  });

  // Sabotage target: drop the `.replace(/</g, '\\u003c')` on the notes JSON.
  it('a notes string with </script> cannot close the notes element', () => {
    // Unquoted id: JSON.stringify would turn quotes into \" and the id would no longer match.
    const hostile = 'x</script><p id=injected>y</p>';
    const html = buildCompositeHtml(deckWithNotes([hostile]));
    const doc = parse(html);

    expect(doc.getElementById('injected')).toBeNull();
    expect(embeddedNotes(doc)).toEqual([hostile]);
    expect(html).not.toContain('</script><p');
  });

  // Sabotage target: omit `notes` from the /pptx/editable/from-images request body.
  it('the screenshot export sends one notes entry per slide', async () => {
    const fetchMock = stubFetch(new Response(new Blob(['pptx']), { status: 200 }));

    await api.exportPptxEditable(deckWithNotes(['Say A.', '']), 's1', 'screenshot');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/api/export/pptx/editable/from-images');
    const body = JSON.parse(String(init?.body));
    expect(body.images).toHaveLength(2);
    expect(body.notes).toEqual(['Say A.', '']);
  });

  // Presenter plan Task 3. Sabotage target: buildCompositeHtml keeps reading speaker_notes alone, or drops the
  // '<' escape on the combined text.
  it('buildCompositeHtml embeds the talk track, then Notes:, then the notes, with < escaped', () => {
    const html = buildCompositeHtml(
      deckWithFields([
        { talk_track: 'Say <b>A</b>.', speaker_notes: 'Know </script> A.' },
        ...TWO_FIELD_SLIDES.slice(1),
      ]),
    );
    const doc = parse(html);
    expect(embeddedNotes(doc)).toEqual(['Say <b>A</b>.\n\nNotes:\nKnow </script> A.', 'Say B.', 'Know C.']);
    const raw = doc.getElementById('speaker-notes')!.textContent!;
    expect(raw).not.toContain('<');
    expect(raw).toContain('Say \\u003cb>A\\u003c/b>.');
  });

  // Presenter plan Task 3. Sabotage target: the from-images body keeps `s.speaker_notes ?? ''`.
  it('the screenshot export sends the talk track, then Notes:, then the notes', async () => {
    const fetchMock = stubFetch(new Response(new Blob(['pptx']), { status: 200 }));
    // The capture mock returns two images; a three-slide deck still sends one notes entry per slide.
    await api.exportPptxEditable(deckWithFields(TWO_FIELD_SLIDES), 's1', 'screenshot');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.notes).toEqual(TWO_FIELD_PANES);
  });
});

describe('presenterPaneText', () => {
  // Sabotage target: notes before the talk track, or a missing or renamed "Notes:" heading.
  it('writes the talk track, then Notes:, then the notes', async () => {
    const presenterPaneText = await loadPresenterPaneText();
    expect(presenterPaneText({ talk_track: 'Say A.', speaker_notes: 'Know B.' })).toBe(
      'Say A.\n\nNotes:\nKnow B.',
    );
  });

  // Sabotage target: always write the "Notes:" heading, or ignore talk_track.
  it('a talk track alone has no heading', async () => {
    const presenterPaneText = await loadPresenterPaneText();
    expect(presenterPaneText({ talk_track: 'Say A.', speaker_notes: '' })).toBe('Say A.');
  });

  // Review Focus 2: a slide stored before the talk track existed exports exactly as before.
  it('a notes-only slide is unchanged', async () => {
    const presenterPaneText = await loadPresenterPaneText();
    expect(presenterPaneText({ speaker_notes: 'Know B.' })).toBe('Know B.');
  });

  it('reads the older notes key when speaker_notes is absent', async () => {
    const presenterPaneText = await loadPresenterPaneText();
    expect(presenterPaneText({ notes: 'old' })).toBe('old');
  });

  // Sabotage target: `speaker_notes || notes`, which brings a cleared note back from a stale key.
  it('cleared notes stay cleared', async () => {
    const presenterPaneText = await loadPresenterPaneText();
    expect(presenterPaneText({ speaker_notes: '', notes: 'old' })).toBe('');
  });

  // Sabotage target: drop the .trim() on either field.
  it('trims each field before joining', async () => {
    const presenterPaneText = await loadPresenterPaneText();
    expect(presenterPaneText({ talk_track: '  Say A.\n', speaker_notes: '\n Know B.  ' })).toBe(
      'Say A.\n\nNotes:\nKnow B.',
    );
    expect(presenterPaneText({ talk_track: '   ', speaker_notes: ' Know B.\n' })).toBe('Know B.');
  });
});
