/**
 * #319 — the chat placeholder shows the graph turn's stage.
 *
 * MessageList renders whatever label ChatPanel hands it, inside a polite, atomic live
 * region.  The no-label text stays byte-identical to the pre-#319 text (three ASCII
 * dots): `chat-ui.spec.ts` pins `/Generating slides/`.  The region carries no
 * `role="status"`, because `mixed-release-collaboration.spec.ts` asserts exactly one
 * status role on its page (plan D22).
 */
import { render, screen, within } from '@testing-library/react';
import { MessageList } from './MessageList';
import type { Message } from '../../types/message';

const oneMessage: Message[] = [
  { role: 'user', content: 'Make me a deck', timestamp: '2026-10-19T00:00:00Z' },
];

const placeholder = () => screen.getByTestId('chat-turn-progress');

describe('MessageList turn-progress placeholder (#319)', () => {
  it('with loading on and no prop, the default text is Generating slides...', () => {
    render(<MessageList messages={oneMessage} isLoading />);
    expect(placeholder().textContent?.trim()).toBe('Generating slides...');
  });

  it('renders the given progressLabel', () => {
    render(
      <MessageList messages={oneMessage} isLoading progressLabel="Reviewing slide 3… (2 of 3 done)" />,
    );
    expect(placeholder().textContent?.trim()).toBe('Reviewing slide 3… (2 of 3 done)');
    expect(screen.queryByText('Generating slides...')).toBeNull();
  });

  it('renders nothing when isLoading is false', () => {
    const { rerender } = render(
      <MessageList messages={oneMessage} isLoading progressLabel="Planning the deck…" />,
    );
    // Non-vacuous: the region exists while loading, so its absence below is the guard.
    expect(placeholder()).toBeInTheDocument();

    rerender(<MessageList messages={oneMessage} isLoading={false} progressLabel="Planning the deck…" />);
    expect(screen.queryByTestId('chat-turn-progress')).toBeNull();
    expect(screen.queryByText('Planning the deck…')).toBeNull();
    expect(screen.queryByText('Generating slides...')).toBeNull();
  });

  it('the wrapper is aria-live="polite" and aria-atomic="true", with no role="status"', () => {
    render(<MessageList messages={oneMessage} isLoading progressLabel="Building 3 slides…" />);
    const region = placeholder();
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-atomic', 'true');
    expect(region).not.toHaveAttribute('role');
    expect(screen.queryByRole('status')).toBeNull();
    // The label is inside the live region, so a change to it is what gets announced.
    expect(within(region).getByText('Building 3 slides…')).toBeInTheDocument();
  });
});
