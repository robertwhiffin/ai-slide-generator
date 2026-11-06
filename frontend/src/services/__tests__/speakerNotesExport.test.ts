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
});
