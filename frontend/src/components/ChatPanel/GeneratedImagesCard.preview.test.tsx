/**
 * @vitest-environment jsdom
 *
 * The options card's full-size preview (user feedback: the chat panel is too small to judge a
 * detailed image from its thumbnail).
 *
 * - Each option has an "Enlarge option N" button (clicking the thumbnail opens it too).
 * - The preview is a dialog named "Option N". It loads the FULL image (`api.getImageData`), not
 *   the 150 px thumbnail, and shows it as "Option N, full size".
 * - Previous / Next (and the arrow keys) step through the card's options; Escape and Close
 *   close it.
 * - "Use this" in the preview picks that option and closes it: only for an option on no slide,
 *   never when the card hides its actions, and disabled while the card's actions are.
 * - A full image that cannot be loaded says so.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImageAsset } from '../../types/image';
import type { GeneratedImageRef } from '../../types/message';
import { GeneratedImagesCard } from './GeneratedImagesCard';
import { __clearFullImageCacheForTests } from '../../utils/fullImageCache';

const h = vi.hoisted(() => ({ getImage: vi.fn(), getImageData: vi.fn() }));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      getImage: (...args: unknown[]) => h.getImage(...args),
      getImageData: (...args: unknown[]) => h.getImageData(...args),
    },
  };
});

const full = (token: string) => `data:image/jpeg;base64,FULL_${token}`;

function asset(token: string): ImageAsset {
  return {
    id: token,
    filename: `${token}.jpg`,
    original_filename: `${token}.jpg`,
    mime_type: 'image/jpeg',
    size_bytes: 1024,
    thumbnail_base64: `data:image/jpeg;base64,THUMB_${token}`,
    tags: ['ai_generated', 'chat', 'chat_option'],
    description: null,
    category: 'content',
    uploaded_by: 'alice@example.com',
    is_active: true,
    created_at: '2026-11-09T10:00:00Z',
    updated_at: '2026-11-09T10:00:00Z',
  };
}

const ref = (option: number, over: Partial<GeneratedImageRef> = {}): GeneratedImageRef => ({
  token: `tok${option}`,
  kind: 'illustration',
  option,
  prompt: 'A calm lake at dawn',
  for_slide: 2,
  slides: [],
  ...over,
});

const THREE = [ref(1), ref(2), ref(3)];

function renderCard(props: Partial<ComponentProps<typeof GeneratedImagesCard>> = {}) {
  const onUse = vi.fn();
  const onRegenerate = vi.fn();
  render(<GeneratedImagesCard images={THREE} onUse={onUse} onRegenerate={onRegenerate} {...props} />);
  return { onUse, onRegenerate };
}

const dialog = () => screen.getByRole('dialog');
const queryDialog = () => screen.queryByRole('dialog');
const enlarge = (n: number) => screen.getByRole('button', { name: `Enlarge option ${n}` });
const fullImage = (n: number) => within(dialog()).findByRole('img', { name: `Option ${n}, full size` });

beforeEach(() => {
  __clearFullImageCacheForTests();
  h.getImage.mockReset();
  h.getImage.mockImplementation(async (token: string) => asset(token));
  h.getImageData.mockReset();
  h.getImageData.mockImplementation(async (token: string) => ({
    id: token,
    mime_type: 'image/jpeg',
    base64_data: `FULL_${token}`,
    data_uri: full(token),
  }));
});
afterEach(() => cleanup());

describe('GeneratedImagesCard: full-size preview', () => {
  it('gives every option an Enlarge button, and opens nothing until one is clicked', () => {
    renderCard();

    for (const n of [1, 2, 3]) expect(enlarge(n)).toBeInTheDocument();
    expect(queryDialog()).toBeNull();
    expect(h.getImageData).not.toHaveBeenCalled();
  });

  it('opens a dialog for that option with the full image, not the thumbnail', async () => {
    renderCard();

    fireEvent.click(enlarge(2));

    expect(dialog()).toHaveAccessibleName('Option 2');
    const img = await fullImage(2);
    expect(img).toHaveAttribute('src', full('tok2'));
    expect(h.getImageData).toHaveBeenCalledWith('tok2');
  });

  it('clicking the thumbnail opens the preview too', async () => {
    renderCard();
    const thumb = await screen.findByRole('img', { name: 'Option 3' });

    fireEvent.click(thumb);

    expect(dialog()).toHaveAccessibleName('Option 3');
    await fullImage(3);
  });

  it('Previous and Next step through the options, and stop at the ends', async () => {
    renderCard();
    fireEvent.click(enlarge(1));
    await fullImage(1);

    expect(within(dialog()).getByRole('button', { name: 'Previous option' })).toBeDisabled();
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Next option' }));
    expect(dialog()).toHaveAccessibleName('Option 2');
    await fullImage(2);
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Next option' }));
    expect(dialog()).toHaveAccessibleName('Option 3');
    await fullImage(3);
    expect(within(dialog()).getByRole('button', { name: 'Next option' })).toBeDisabled();

    fireEvent.click(within(dialog()).getByRole('button', { name: 'Previous option' }));
    expect(dialog()).toHaveAccessibleName('Option 2');
    await fullImage(2);
    // Stepping back shows the image already loaded: it is not fetched again.
    expect(h.getImageData.mock.calls.map((c) => c[0])).toEqual(['tok1', 'tok2', 'tok3']);
  });

  it('the arrow keys step through the options and Escape closes', async () => {
    renderCard();
    fireEvent.click(enlarge(2));
    await fullImage(2);

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(dialog()).toHaveAccessibleName('Option 3');
    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(dialog()).toHaveAccessibleName('Option 1');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(queryDialog()).toBeNull();
  });

  it('Close closes it', async () => {
    renderCard();
    fireEvent.click(enlarge(1));
    await fullImage(1);

    fireEvent.click(within(dialog()).getByRole('button', { name: 'Close' }));

    expect(queryDialog()).toBeNull();
  });

  it('"Use this" in the preview picks that option and closes', async () => {
    const { onUse } = renderCard();
    fireEvent.click(enlarge(2));
    await fullImage(2);

    fireEvent.click(within(dialog()).getByRole('button', { name: 'Use this' }));

    expect(onUse).toHaveBeenCalledTimes(1);
    expect(onUse).toHaveBeenCalledWith(THREE[1]);
    expect(queryDialog()).toBeNull();
  });

  it('a placed option offers no "Use this" in the preview, and says where it is', async () => {
    render(
      <GeneratedImagesCard
        images={[ref(1, { slides: [2] }), ref(2)]}
        onUse={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(enlarge(1));
    await fullImage(1);

    expect(within(dialog()).queryByRole('button', { name: 'Use this' })).toBeNull();
    expect(within(dialog()).getByText('On slide 2')).toBeInTheDocument();
  });

  it('hidden actions (a save-point preview) show no "Use this" in the preview', async () => {
    renderCard({ hideActions: true });
    fireEvent.click(enlarge(1));
    await fullImage(1);

    expect(within(dialog()).queryByRole('button', { name: 'Use this' })).toBeNull();
  });

  it('disabled actions (a turn is running) disable "Use this" in the preview', async () => {
    const { onUse } = renderCard({ actionsDisabled: true });
    fireEvent.click(enlarge(1));
    await fullImage(1);

    const use = within(dialog()).getByRole('button', { name: 'Use this' });
    expect(use).toBeDisabled();
    fireEvent.click(use);
    expect(onUse).not.toHaveBeenCalled();
  });

  it('says so when the full image cannot be loaded', async () => {
    h.getImageData.mockRejectedValue(new Error('404'));
    renderCard();

    await act(async () => {
      fireEvent.click(enlarge(1));
    });

    await waitFor(() =>
      expect(within(dialog()).getByText("Couldn't load the full-size image.")).toBeInTheDocument(),
    );
    expect(within(dialog()).queryByRole('img', { name: 'Option 1, full size' })).toBeNull();
  });
});
