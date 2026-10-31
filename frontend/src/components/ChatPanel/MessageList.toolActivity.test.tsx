/**
 * Tool-call messages collapse into one small, set-back, expandable bar per consecutive run.
 */
import { render, screen, within, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MessageList } from './MessageList';
import type { Message } from '../../types/message';

const TS = '2026-10-29T00:00:00Z';
const call = (name: string, args: Record<string, unknown>): Message => ({
  role: 'assistant',
  content: `Using tool: ${name}`,
  timestamp: TS,
  tool_call: { name, arguments: args },
});
const genie = (q: string) => call('genie_one', { question: q });
const result = (content: string): Message => ({ role: 'tool', content, timestamp: TS, tool_call_id: 'genie_one' });
const assistant = (content: string): Message => ({ role: 'assistant', content, timestamp: TS });

const bars = () => screen.queryAllByTestId('tool-activity-bar');
const open = (bar: HTMLElement) => fireEvent.click(within(bar).getByRole('button'));

describe('MessageList tool activity bar', () => {
  it('collapses 3 genie_one calls into one collapsed bar, expandable to 3 items', () => {
    render(
      <MessageList
        isLoading={false}
        messages={[genie('How many trips?'), genie('Which zip is busiest?'), genie('Fare by month?')]}
      />,
    );
    expect(bars()).toHaveLength(1);
    const bar = bars()[0];
    expect(bar.textContent).toContain('3 tool calls · Genie One');
    expect(bar.className).toContain('text-xs');
    expect(bar.className).toContain('text-muted-foreground');
    expect(bar.className).not.toContain('bg-muted');
    expect(screen.queryByText(/How many trips\?/)).toBeNull();
    expect(screen.queryAllByTestId('tool-activity-item')).toHaveLength(0);

    open(bar);
    const items = screen.getAllByTestId('tool-activity-item');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain('Genie One');
    expect(items[0].textContent).toContain('How many trips?');
    expect(items[1].textContent).toContain('Which zip is busiest?');
    expect(items[2].textContent).toContain('Fare by month?');
  });

  it('lists distinct display names in first-seen order', () => {
    render(
      <MessageList
        isLoading={false}
        messages={[genie('a'), call('mcp', { query: 'x' }), genie('b'), call('mcp', { query: 'y' })]}
      />,
    );
    expect(bars()).toHaveLength(1);
    expect(bars()[0].textContent).toContain('4 tool calls · Genie One, MCP Server');
  });

  it('falls back to the raw name for unknown tools and summarises args as key: value', () => {
    render(<MessageList isLoading={false} messages={[call('my_custom_tool', { a: 1, b: 'two' })]} />);
    expect(bars()[0].textContent).toContain('1 tool call · my_custom_tool');
    open(bars()[0]);
    const item = screen.getByTestId('tool-activity-item');
    expect(item.textContent).toContain('my_custom_tool');
    expect(item.textContent).toContain('a: 1');
    expect(item.textContent).toContain('b: two');
    expect(item.textContent).not.toContain('{');
  });

  it('truncates a long argument summary to 120 chars', () => {
    render(<MessageList isLoading={false} messages={[call('mcp', { query: 'z'.repeat(400) })]} />);
    open(bars()[0]);
    const text = screen.getByTestId('tool-activity-item').textContent ?? '';
    expect(text).toContain('query: zzz');
    expect(text).not.toContain('z'.repeat(200));
  });

  it('shows a legacy tool result as a truncated line on expand, with no card', () => {
    render(<MessageList isLoading={false} messages={[genie('How many trips?'), result('R'.repeat(500))]} />);
    expect(bars()).toHaveLength(1);
    expect(bars()[0].textContent).toContain('1 tool call · Genie One');
    expect(bars()[0].textContent).not.toContain('RRRRRRRRRR');
    open(bars()[0]);
    expect(screen.getAllByTestId('tool-activity-item')).toHaveLength(1);
    const text = bars()[0].textContent ?? '';
    expect(text).toContain('RRRRRRRRRR');
    expect(text).not.toContain('R'.repeat(200));
    expect(screen.queryByText(/Tool call:/)).toBeNull();
    expect(screen.queryByText(/Tool result/i)).toBeNull();
  });

  it('a non-tool message between runs makes two bars', () => {
    render(
      <MessageList
        isLoading={false}
        messages={[genie('one'), genie('two'), assistant('Here is what I found'), genie('three')]}
      />,
    );
    expect(bars()).toHaveLength(2);
    expect(bars()[0].textContent).toContain('2 tool calls · Genie One');
    expect(bars()[1].textContent).toContain('1 tool call · Genie One');
    expect(screen.getByText('Here is what I found')).toBeInTheDocument();
  });

  it('uses the singular label for one call', () => {
    render(<MessageList isLoading={false} messages={[genie('solo')]} />);
    expect(bars()[0].textContent).toContain('1 tool call · Genie One');
    expect(bars()[0].textContent).not.toContain('1 tool calls');
  });

  it('never renders JSON, collapsed or expanded', () => {
    const { container } = render(
      <MessageList isLoading={false} messages={[genie('How many trips?'), result('{"rows": 3}')]} />,
    );
    expect(container.textContent).not.toContain('{"question"');
    open(bars()[0]);
    expect(container.textContent).not.toContain('{"question"');
    expect(container.textContent).not.toContain('"question":');
  });
});
