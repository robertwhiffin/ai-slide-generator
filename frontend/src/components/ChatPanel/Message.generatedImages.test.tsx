/**
 * @vitest-environment jsdom
 *
 * Controller addition (chat image generation, Unit I): the options card belongs under an
 * assistant reply only. Generated images arrive on the architect's reply row; a user, tool or
 * system message never shows the card, whatever its metadata says.
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Message } from './Message';
import type { GeneratedImageRef, Message as MessageType } from '../../types/message';

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, api: { getImage: vi.fn().mockRejectedValue(new Error('no image')) } };
});

const IMAGES: GeneratedImageRef[] = [
  { token: 'tok1', kind: 'illustration', option: 1, for_slide: 2, slides: [] },
  { token: 'tok2', kind: 'illustration', option: 2, for_slide: 2, slides: [] },
];

const actions = { onUse: vi.fn(), onRegenerate: vi.fn(), disabled: false, hidden: false };

function message(role: MessageType['role']): MessageType {
  return {
    role,
    content: 'Here are some options.',
    timestamp: '2026-11-09T10:00:00Z',
    generated_images: IMAGES,
  } as MessageType;
}

afterEach(() => cleanup());

describe('Message: the generated-images card', () => {
  it('shows under an assistant reply', () => {
    render(<Message message={message('assistant')} imageActions={actions} />);

    expect(screen.getByTestId('generated-images-card')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Use this' })).toHaveLength(2);
  });

  it.each(['user', 'tool'] as const)('never shows under a %s message', (role) => {
    render(<Message message={message(role)} imageActions={actions} />);

    expect(screen.queryByTestId('generated-images-card')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Use this' })).toBeNull();
  });
});
