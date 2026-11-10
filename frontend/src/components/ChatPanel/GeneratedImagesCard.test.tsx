/**
 * Chat image generation, Unit I (Task 7): the options card under an architect reply that generated
 * images.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface",
 * `GeneratedImagesCard` (components/ChatPanel/GeneratedImagesCard.tsx, named export):
 *   props {images, onUse(img), onRegenerate(images), actionsDisabled?, hideActions?}
 *   - for each image: a thumbnail loaded with `api.getImage(token)` (its `thumbnail_base64`, already a
 *     data URI, is the <img> src), or a placeholder when that rejects or has no thumbnail;
 *     and an "Option N" label;
 *   - an "On slide N" badge per entry of `slides`;
 *   - a "Use this" button only on an image whose `slides` is empty;
 *   - exactly one "Regenerate" button for the card;
 *   - the caption "Saved to your Image Library".
 *
 * DOM contract the implementer must match (roles and names, not classes):
 *   - each option is a list item (<li>) holding the visible text "Option N" (exact);
 *   - its thumbnail is an <img> whose accessible name starts with "Option N" (alt="Option N" is fine);
 *   - its placeholder is NOT an img (no <img>, no role="img") and carries
 *     data-testid="generated-image-placeholder";
 *   - buttons are named exactly "Use this" and "Regenerate".
 *
 * Choices this test pins (CORRECTIONS is silent): getImage is asked once per token; Use hands back the
 * very ref it was rendered from; Regenerate hands back the card's whole `images` list; with
 * `hideActions` the thumbnails, labels and badges still render.
 */
import type { ComponentProps } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImageAsset } from '../../types/image';
import type { GeneratedImageRef } from '../../types/message';
import { GeneratedImagesCard } from './GeneratedImagesCard';

const h = vi.hoisted(() => ({ getImage: vi.fn() }));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, api: { getImage: (...args: unknown[]) => h.getImage(...args) } };
});

const thumb = (token: string) => `data:image/png;base64,THUMB_${token}`;

function asset(token: string, overrides: Partial<ImageAsset> = {}): ImageAsset {
  return {
    id: token,
    filename: `${token}.png`,
    original_filename: `${token}.png`,
    mime_type: 'image/png',
    size_bytes: 1024,
    thumbnail_base64: thumb(token),
    tags: ['ai_generated', 'chat', 'chat_option'],
    description: null,
    category: 'content',
    uploaded_by: 'alice@example.com',
    is_active: true,
    created_at: '2026-11-09T10:00:00Z',
    updated_at: '2026-11-09T10:00:00Z',
    ...overrides,
  };
}

const ref = (option: number, over: Partial<GeneratedImageRef> = {}): GeneratedImageRef => ({
  token: `tok${option}`,
  kind: 'illustration',
  option,
  prompt: 'A calm lake at dawn',
  for_slide: 3,
  slides: [],
  ...over,
});

const THREE = [ref(1), ref(2), ref(3)];

// ── queries ───────────────────────────────────────────────────────────────────

/** The list item holding the visible label "Option N". */
function tile(n: number): HTMLElement {
  const label = screen.getByText(`Option ${n}`, { exact: true });
  const li = label.closest('li');
  expect(li, `"Option ${n}" sits in a list item`).not.toBeNull();
  return li as HTMLElement;
}

const useButtons = () => screen.queryAllByRole('button', { name: 'Use this' });
const regenerateButtons = () => screen.queryAllByRole('button', { name: 'Regenerate' });

function renderCard(props: Partial<ComponentProps<typeof GeneratedImagesCard>> = {}) {
  const onUse = vi.fn();
  const onRegenerate = vi.fn();
  render(<GeneratedImagesCard images={THREE} onUse={onUse} onRegenerate={onRegenerate} {...props} />);
  return { onUse, onRegenerate };
}

beforeEach(() => {
  h.getImage.mockReset();
  h.getImage.mockImplementation(async (token: string) => asset(token));
});
afterEach(() => cleanup());

// ── tests ─────────────────────────────────────────────────────────────────────

describe('GeneratedImagesCard: thumbnails and labels', () => {
  it('renders 3 options labelled Option 1..3, each with its own thumbnail from api.getImage', async () => {
    renderCard();

    for (const n of [1, 2, 3]) {
      const img = await within(tile(n)).findByRole('img', { name: new RegExp(`^Option ${n}\\b`) });
      expect(img).toHaveAttribute('src', thumb(`tok${n}`));
    }
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getAllByRole('img')).toHaveLength(3);
    expect(h.getImage.mock.calls.map((c) => c[0]).sort()).toEqual(['tok1', 'tok2', 'tok3']);
  });

  it('shows a placeholder, not a broken image, when getImage rejects', async () => {
    h.getImage.mockImplementation(async (token: string) => {
      if (token === 'tok2') throw new Error('404 Not Found');
      return asset(token);
    });
    renderCard();

    await within(tile(1)).findByRole('img');
    await within(tile(3)).findByRole('img');
    await waitFor(() => expect(within(tile(2)).getByTestId('generated-image-placeholder')).toBeInTheDocument());
    expect(within(tile(2)).queryByRole('img')).toBeNull();
    expect(tile(2).querySelector('img')).toBeNull();
    // The option stays usable: its label and its Use button are still there.
    expect(within(tile(2)).getByRole('button', { name: 'Use this' })).toBeInTheDocument();
  });

  it('shows a placeholder when the image has no thumbnail', async () => {
    h.getImage.mockImplementation(async (token: string) =>
      asset(token, token === 'tok3' ? { thumbnail_base64: null } : {}),
    );
    renderCard();

    await within(tile(1)).findByRole('img');
    await waitFor(() => expect(within(tile(3)).getByTestId('generated-image-placeholder')).toBeInTheDocument());
    expect(tile(3).querySelector('img')).toBeNull();
  });

  it('shows the caption "Saved to your Image Library"', () => {
    renderCard();
    expect(screen.getByText('Saved to your Image Library')).toBeInTheDocument();
  });
});

describe('GeneratedImagesCard: placed images and actions', () => {
  it('badges a placed image "On slide 2" and offers "Use this" only on the unplaced ones', async () => {
    renderCard({ images: [ref(1), ref(2, { slides: [2] }), ref(3)] });

    expect(within(tile(2)).getByText('On slide 2')).toBeInTheDocument();
    expect(within(tile(2)).queryByRole('button', { name: 'Use this' })).toBeNull();
    expect(within(tile(1)).getByRole('button', { name: 'Use this' })).toBeInTheDocument();
    expect(within(tile(3)).getByRole('button', { name: 'Use this' })).toBeInTheDocument();
    expect(useButtons()).toHaveLength(2);
    expect(screen.queryByText(/^On slide/)).toBe(within(tile(2)).getByText('On slide 2'));
  });

  it('badges every slide an image is on', () => {
    renderCard({ images: [ref(1, { slides: [2, 4] })] });

    expect(within(tile(1)).getByText('On slide 2')).toBeInTheDocument();
    expect(within(tile(1)).getByText('On slide 4')).toBeInTheDocument();
    expect(useButtons()).toHaveLength(0);
  });

  it('an unplaced image shows no badge', () => {
    renderCard();
    expect(screen.queryByText(/On slide/)).toBeNull();
    expect(useButtons()).toHaveLength(3);
  });

  it('"Use this" hands back that option’s ref', () => {
    const { onUse, onRegenerate } = renderCard();

    fireEvent.click(within(tile(2)).getByRole('button', { name: 'Use this' }));

    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onUse).toHaveBeenCalledWith(THREE[1]);
    expect(onRegenerate).not.toHaveBeenCalled();
  });

  it('has exactly one "Regenerate", which hands back the whole set', () => {
    const { onUse, onRegenerate } = renderCard();

    expect(regenerateButtons()).toHaveLength(1);
    fireEvent.click(regenerateButtons()[0]);

    expect(onRegenerate).toHaveBeenCalledTimes(1);
    expect(onRegenerate).toHaveBeenCalledWith(THREE);
    expect(onUse).not.toHaveBeenCalled();
  });

  it('a single placed image still offers Regenerate', () => {
    renderCard({ images: [ref(1, { slides: [1] })] });
    expect(useButtons()).toHaveLength(0);
    expect(regenerateButtons()).toHaveLength(1);
  });

  it('actionsDisabled disables every action; clicks do nothing', () => {
    const { onUse, onRegenerate } = renderCard({ actionsDisabled: true });

    expect(useButtons()).toHaveLength(3);
    for (const b of useButtons()) expect(b).toBeDisabled();
    expect(regenerateButtons()).toHaveLength(1);
    expect(regenerateButtons()[0]).toBeDisabled();

    for (const b of [...useButtons(), ...regenerateButtons()]) fireEvent.click(b);
    expect(onUse).not.toHaveBeenCalled();
    expect(onRegenerate).not.toHaveBeenCalled();
  });

  it('without actionsDisabled the actions are enabled', () => {
    renderCard();
    for (const b of [...useButtons(), ...regenerateButtons()]) expect(b).toBeEnabled();
  });

  it('hideActions renders no buttons but keeps the options, thumbnails and badges', async () => {
    renderCard({ images: [ref(1), ref(2, { slides: [2] }), ref(3)], hideActions: true });

    expect(useButtons()).toHaveLength(0);
    expect(regenerateButtons()).toHaveLength(0);
    for (const n of [1, 2, 3]) await within(tile(n)).findByRole('img');
    expect(within(tile(2)).getByText('On slide 2')).toBeInTheDocument();
  });
});
