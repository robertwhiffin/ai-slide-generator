/**
 * McpAgentChoice: the "Which agent uses it?" radio group on the MCP Server panels.
 * A <fieldset> with a legend and two radios; the Data analyst comes first. Each label is the
 * bold agent name, then " · ", then its hint.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { McpAgentChoice } from './McpAgentChoice';

const ANALYST_HINT = 'fetches data: figures for charts and tables';
const ARCHITECT_HINT =
  'fetches other context for planning the slides: documents, pages, references';

describe('McpAgentChoice', () => {
  it('renders the legend and both radios with the exact copy', () => {
    const { container } = render(<McpAgentChoice value="data_analyst" onChange={vi.fn()} />);

    const group = screen.getByRole('group', { name: 'Which agent uses it?' });
    expect(group.tagName).toBe('FIELDSET');
    expect(container.querySelector('legend')?.textContent).toBe('Which agent uses it?');

    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(radios).toHaveLength(2);
    // Data analyst first.
    expect(radios[0].labels?.[0]?.textContent).toBe(`Data analyst · ${ANALYST_HINT}`);
    expect(radios[1].labels?.[0]?.textContent).toBe(`Architect · ${ARCHITECT_HINT}`);

    // The agent name is the bold part of each label.
    const bold = Array.from(container.querySelectorAll('label strong, label b')).map(
      (n) => n.textContent,
    );
    expect(bold).toEqual(['Data analyst', 'Architect']);
  });

  it('Data analyst is checked when value is data_analyst', () => {
    render(<McpAgentChoice value="data_analyst" onChange={vi.fn()} />);
    const [analyst, architect] = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(analyst.checked).toBe(true);
    expect(architect.checked).toBe(false);
  });

  it('Architect is checked when value is architect', () => {
    render(<McpAgentChoice value="architect" onChange={vi.fn()} />);
    const [analyst, architect] = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(analyst.checked).toBe(false);
    expect(architect.checked).toBe(true);
  });

  it("choosing Architect calls onChange('architect')", () => {
    const onChange = vi.fn();
    render(<McpAgentChoice value="data_analyst" onChange={onChange} />);
    fireEvent.click(screen.getByRole('radio', { name: /^Architect/ }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('architect');
  });

  it('two instances do not share a radio group', () => {
    render(
      <>
        <McpAgentChoice value="data_analyst" onChange={vi.fn()} />
        <McpAgentChoice value="architect" onChange={vi.fn()} />
      </>,
    );
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(radios[0].name).toBeTruthy();
    expect(radios[0].name).toBe(radios[1].name);
    expect(radios[2].name).toBe(radios[3].name);
    expect(radios[0].name).not.toBe(radios[2].name);
    // Each keeps its own checked state.
    expect(radios.map((r) => r.checked)).toEqual([true, false, false, true]);
  });
});
