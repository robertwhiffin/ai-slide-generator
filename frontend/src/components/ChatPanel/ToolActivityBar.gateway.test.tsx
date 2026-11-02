/**
 * Gateway MCP Task 7 (PLAN-CORRECTIONS T7.5): a Gateway tool call's progress row carries
 * metadata = {tool_name: "gateway_mcp", tool_input: {connection: <display_name>, tool: <mcp tool>}}
 * (T6.8). ChatPanel maps that to tool_call {name, arguments}. The activity bar renders the row as
 * "{connection} · {tool}", as Genie One's rows read "Genie One · <question>", and names the
 * connection (not the generic type) in the collapsed summary.
 */
import { render, screen, within, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ToolActivityBar } from './ToolActivityBar';
import type { Message } from '../../types/message';

const TS = '2026-11-02T00:00:00Z';

const gateway = (args: Record<string, unknown>): Message => ({
  role: 'assistant',
  content: 'Using tool: gateway_mcp',
  timestamp: TS,
  tool_call: { name: 'gateway_mcp', arguments: args },
});
const genie = (q: string): Message => ({
  role: 'assistant',
  content: 'Using tool: genie_one',
  timestamp: TS,
  tool_call: { name: 'genie_one', arguments: { question: q } },
});

const bar = () => screen.getByTestId('tool-activity-bar');
const open = () => fireEvent.click(within(bar()).getByRole('button'));
const items = () => screen.getAllByTestId('tool-activity-item');

describe('ToolActivityBar: gateway_mcp rows', () => {
  it('renders a gateway_mcp row as "LakeDraw · lakedraw_create_from_spec"', () => {
    render(
      <ToolActivityBar
        messages={[gateway({ connection: 'LakeDraw', tool: 'lakedraw_create_from_spec' })]}
      />,
    );

    expect(bar().textContent).toContain('1 tool call · LakeDraw');
    open();
    expect(items()).toHaveLength(1);
    expect(items()[0].textContent).toBe('LakeDraw · lakedraw_create_from_spec');
    expect(items()[0].textContent).not.toContain('connection:');
  });

  it('names each connection alongside other tools, in first-seen order', () => {
    render(
      <ToolActivityBar
        messages={[
          genie('How many trips?'),
          gateway({ connection: 'LakeDraw', tool: 'lakedraw_create_from_spec' }),
          gateway({ connection: 'Web Search', tool: 'web_search' }),
        ]}
      />,
    );

    expect(bar().textContent).toContain('3 tool calls · Genie One, LakeDraw, Web Search');
    open();
    expect(items().map((i) => i.textContent)).toEqual([
      'Genie One · How many trips?',
      'LakeDraw · lakedraw_create_from_spec',
      'Web Search · web_search',
    ]);
  });

  it('falls back to the "AI Gateway MCP" label when the row carries no connection', () => {
    render(<ToolActivityBar messages={[gateway({})]} />);

    expect(bar().textContent).toContain('1 tool call · AI Gateway MCP');
    open();
    expect(items()[0].textContent).toBe('AI Gateway MCP');
    expect(items()[0].textContent).not.toContain('undefined');
  });
});
