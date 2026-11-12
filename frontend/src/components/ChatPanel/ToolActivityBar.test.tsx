/**
 * A Genie Agent's progress row arrives as tool_call {name: 'genie', arguments: {agent, question}}.
 * The activity bar names the row after the agent (the space the user chose), with the question
 * as its summary, as Genie One's rows read "Genie One · <question>".
 */
import { render, screen, within, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ToolActivityBar } from './ToolActivityBar';
import type { Message } from '../../types/message';

const TS = '2026-11-12T00:00:00Z';

const genieAgent = (args: Record<string, unknown>): Message => ({
  role: 'assistant',
  content: 'Using tool: genie',
  timestamp: TS,
  tool_call: { name: 'genie', arguments: args },
});

const bar = () => screen.getByTestId('tool-activity-bar');
const open = () => fireEvent.click(within(bar()).getByRole('button'));
const items = () => screen.getAllByTestId('tool-activity-item');

describe('ToolActivityBar: Genie Agent rows', () => {
  it('a genie row is named after its agent', () => {
    render(
      <ToolActivityBar
        messages={[genieAgent({ agent: 'Sales Insights', question: 'Top 5 regions by revenue?' })]}
      />,
    );

    expect(bar().textContent).toContain('1 tool call · Sales Insights');
    open();
    expect(items()).toHaveLength(1);
    expect(items()[0].textContent).toBe('Sales Insights · Top 5 regions by revenue?');
    expect(items()[0].textContent).not.toContain('agent:');
  });

  it('names each agent once in the collapsed summary, in first-seen order', () => {
    render(
      <ToolActivityBar
        messages={[
          genieAgent({ agent: 'Sales Insights', question: 'q1' }),
          genieAgent({ agent: 'HR Data', question: 'q2' }),
          genieAgent({ agent: 'Sales Insights', question: 'q3' }),
        ]}
      />,
    );
    expect(bar().textContent).toContain('3 tool calls · Sales Insights, HR Data');
  });
});
