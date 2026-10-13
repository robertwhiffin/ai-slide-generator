/**
 * The empty chat explains how deck generation works today.
 *
 * Returning users skip the app tour, so the empty conversation is the one place
 * every user sees before their first message on a new deck. The guide must
 * show only then: never once a conversation exists, and not while the first
 * message is generating.
 *
 * Sabotage targets: drop the `messages.length === 0` guard in MessageList;
 * drop the `!isLoading` guard.
 */
import { render, screen } from '@testing-library/react';
import { MessageList } from './MessageList';
import type { Message } from '../../types/message';

beforeAll(() => {
  // jsdom has no layout; MessageList auto-scrolls on every message change.
  Element.prototype.scrollIntoView = vi.fn();
});

const GUIDE = { name: /how tellr builds your deck/i };

const oneMessage: Message[] = [
  { role: 'user', content: 'Make me a deck', timestamp: '2026-10-13T00:00:00Z' },
];

describe('ChatWelcome in the empty chat', () => {
  it('shows the guide when the conversation is empty', () => {
    render(<MessageList messages={[]} isLoading={false} />);
    expect(screen.getByRole('heading', GUIDE)).toBeInTheDocument();
  });

  it('leads with Tellr as an interviewer, not a slide generator', () => {
    render(<MessageList messages={[]} isLoading={false} />);
    expect(screen.getByText(/start with an idea, not a brief/i)).toBeInTheDocument();
    expect(screen.getByText(/it will interview you/i)).toBeInTheDocument();
  });

  it('teaches editing by slide number and the deck-wide and data paths', () => {
    render(<MessageList messages={[]} isLoading={false} />);
    expect(screen.getByText(/make slide 3 more concise/i)).toBeInTheDocument();
    expect(screen.getByText(/rewrite this for a board audience/i)).toBeInTheDocument();
    expect(screen.getByText(/agent config bar/i)).toBeInTheDocument();
  });

  it('is gone once the conversation has a message', () => {
    render(<MessageList messages={oneMessage} isLoading={false} />);
    expect(screen.queryByRole('heading', GUIDE)).not.toBeInTheDocument();
  });

  it('is gone while the first message is generating', () => {
    render(<MessageList messages={[]} isLoading={true} />);
    expect(screen.queryByRole('heading', GUIDE)).not.toBeInTheDocument();
  });
});
