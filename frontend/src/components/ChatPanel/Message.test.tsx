/**
 * A plain-language failure notice carries its technical detail (stage, error, request id) as
 * `message.details`. Message renders it as a collapsed Details disclosure under ASSISTANT
 * messages only; the headline stays the message content. Rows without details — every row
 * written before #321 — must render exactly as before, with no disclosure.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { Message } from './Message';
import type { Message as MessageType } from '../../types/message';

const NOTICE = "Slide 2 couldn't be built, so it's shown as a placeholder. Ask me to regenerate slide 2.";

function message(overrides: Partial<MessageType>): MessageType {
  return { role: 'assistant', content: NOTICE, timestamp: '2026-10-19T00:00:00Z', ...overrides };
}

describe('Message details disclosure', () => {
  it('renders a closed Details disclosure under an assistant message that has details', () => {
    render(
      <Message
        message={message({
          details: { stage: 'builder', error: 'RuntimeError', request_id: 'req-123' },
        })}
      />,
    );

    // The headline is still the message content.
    expect(screen.getByText(NOTICE)).toBeInTheDocument();

    const disclosures = screen.getAllByTestId('message-details');
    expect(disclosures).toHaveLength(1);
    const details = disclosures[0] as HTMLDetailsElement;

    // The disclosure sits beside the headline, not inside it: the headline's text stays exactly the notice.
    const headline = screen.getByText(NOTICE);
    expect(headline.textContent).toBe(NOTICE);
    expect(headline.contains(details)).toBe(false);

    // Closed by default: a native <details> without the `open` attribute.
    expect(details.tagName).toBe('DETAILS');
    expect(details.open).toBe(false);
    expect(details.hasAttribute('open')).toBe(false);

    const summary = details.querySelector('summary');
    expect(summary).not.toBeNull();
    expect(summary!.textContent).toBe('Details');
    expect(summary).toBeVisible();

    // Each key renders under its human label, paired with its value, inside the disclosure.
    const pairs = Array.from(details.querySelectorAll('dt')).map(dt => [
      dt.textContent,
      dt.nextElementSibling?.tagName,
      dt.nextElementSibling?.textContent,
    ]);
    expect(pairs).toEqual([
      ['Stage', 'DD', 'builder'],
      ['Error', 'DD', 'RuntimeError'],
      ['Request ID', 'DD', 'req-123'],
    ]);

    const values = ['builder', 'RuntimeError', 'req-123'].map(v => within(details).getByText(v));
    const labels = ['Stage', 'Error', 'Request ID'].map(l => within(details).getByText(l));

    // Collapsed: neither the labels nor the values are visible until the disclosure is opened.
    for (const el of [...values, ...labels]) expect(el).not.toBeVisible();

    details.open = true;

    for (const el of [...values, ...labels]) expect(el).toBeVisible();
  });

  it('renders no disclosure for a user message, even one that carries details', () => {
    render(
      <Message
        message={message({
          role: 'user',
          content: 'make slide 2 about revenue',
          details: { stage: 'builder', error: 'RuntimeError', request_id: 'req-123' },
        })}
      />,
    );

    expect(screen.getByText('make slide 2 about revenue')).toBeInTheDocument();
    expect(screen.queryByTestId('message-details')).toBeNull();
    expect(screen.queryByText('Details')).toBeNull();
    expect(screen.queryByText('req-123')).toBeNull();
  });

  it('renders no disclosure for an assistant message without details (a pre-#321 row)', () => {
    render(<Message message={message({})} />);

    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByTestId('message-details')).toBeNull();
    expect(screen.queryByText('Details')).toBeNull();
  });

  it('renders no disclosure for an assistant message whose details are empty', () => {
    render(<Message message={message({ details: {} })} />);

    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByTestId('message-details')).toBeNull();
    expect(screen.queryByText('Details')).toBeNull();
  });
});

describe('Message data analyst card', () => {
  const REPORT =
    'Trips rose 4% in zip 10001. Details follow.\n\n| zip | trips |\n| 10001 | 1227 |\n\nSQL: SELECT 1\nSources: Genie One';

  const analyst = (overrides: Partial<MessageType> = {}) =>
    message({ content: REPORT, agent: 'data_analyst', ...overrides } as Partial<MessageType>);

  it('renders a violet card labelled "Data analyst"', () => {
    render(<Message message={analyst()} />);

    const card = screen.getByTestId('analyst-report');
    expect(within(card).getByText('Data analyst')).toBeInTheDocument();
    const classes = [card, ...Array.from(card.querySelectorAll('*'))]
      .map(el => el.getAttribute('class') ?? '')
      .join(' ');
    expect(classes).toContain('violet');
  });

  it('is collapsed by default and previews the first sentence', () => {
    render(<Message message={analyst()} />);

    // The first sentence, with or without its closing full stop; nothing after it.
    expect(screen.getByText(/^Trips rose 4% in zip 10001\.?$/)).toBeInTheDocument();
    expect(screen.queryByText(/Details follow/)).toBeNull();
    expect(screen.queryByText(/\| 10001 \| 1227 \|/)).toBeNull();
    expect(screen.queryByText(/Sources: Genie One/)).toBeNull();
  });

  it('caps a long first sentence at 140 characters with an ellipsis', () => {
    render(<Message message={analyst({ content: 'x'.repeat(300) })} />);

    // Capped at 140 characters: 139 + the ellipsis, or 140 then the ellipsis.
    expect(screen.getByText(/^x{139,140}…$/)).toBeInTheDocument();
  });

  it('expands on click to the full content, whitespace preserved', () => {
    render(<Message message={analyst()} />);

    fireEvent.click(within(screen.getByTestId('analyst-report')).getByRole('button'));

    const full = screen.getByText((_, el) => el?.tagName === 'PRE' && el.textContent === REPORT);
    expect(full.textContent).toContain('| 10001 | 1227 |');
  });

  it('leaves a normal assistant message without agent as before', () => {
    render(<Message message={message({ content: REPORT })} />);

    expect(screen.queryByTestId('analyst-report')).toBeNull();
    expect(screen.queryByText('Data analyst')).toBeNull();
    expect(screen.getByText(/\| 10001 \| 1227 \|/)).toBeInTheDocument();
  });
});
