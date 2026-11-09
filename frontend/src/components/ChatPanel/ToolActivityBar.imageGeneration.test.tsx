/**
 * Chat image generation, Unit I (Task 6): the activity row for the architect's image tool.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Activity labels":
 * `image_generation` with tool_input {kind, count} reads "Image generation · 3 illustrations".
 * The progress row is persisted as metadata {tool_name: "image_generation", tool_input: {kind, count}}
 * (Unit H) and mapped by ChatPanel to tool_call {name, arguments}.
 *
 * Choices pinned here where CORRECTIONS is silent, from its kind labels (illustration/illustrations,
 * icon/icons, background/backgrounds, vector icon/vector icons):
 *   - count 1 uses the singular ("1 icon"), any other count the plural;
 *   - without a usable kind/count the row reads just "Image generation" (never "undefined", never raw
 *     "kind: …, count: …").
 * ChatPanel's own wiring of the same row (live and reloaded) is in ChatPanel.generatedImages.test.tsx.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ToolActivityBar } from './ToolActivityBar';
import type { Message } from '../../types/message';

const TS = '2026-11-09T10:00:00Z';
const imageCall = (args: Record<string, unknown>): Message => ({
  role: 'assistant',
  content: 'Using tool: image_generation',
  timestamp: TS,
  tool_call: { name: 'image_generation', arguments: args },
});

const bar = () => screen.getByTestId('tool-activity-bar');
const open = () => fireEvent.click(within(bar()).getByRole('button'));
const items = () => screen.getAllByTestId('tool-activity-item').map((i) => i.textContent);

describe('ToolActivityBar: image_generation rows', () => {
  it.each([
    [{ kind: 'illustration', count: 3 }, 'Image generation · 3 illustrations'],
    [{ kind: 'icon', count: 3 }, 'Image generation · 3 icons'],
    [{ kind: 'background', count: 2 }, 'Image generation · 2 backgrounds'],
    [{ kind: 'vector_icon', count: 3 }, 'Image generation · 3 vector icons'],
    [{ kind: 'icon', count: 1 }, 'Image generation · 1 icon'],
    [{ kind: 'vector_icon', count: 1 }, 'Image generation · 1 vector icon'],
    [{ kind: 'illustration', count: 1 }, 'Image generation · 1 illustration'],
  ])('%j reads %s', (args, expected) => {
    render(<ToolActivityBar messages={[imageCall(args)]} />);

    expect(bar().textContent).toContain('1 tool call · Image generation');
    open();
    expect(items()).toEqual([expected]);
  });

  it('two calls in one turn read as two rows under one name', () => {
    render(
      <ToolActivityBar
        messages={[imageCall({ kind: 'illustration', count: 3 }), imageCall({ kind: 'icon', count: 1 })]}
      />,
    );

    expect(bar().textContent).toContain('2 tool calls · Image generation');
    open();
    expect(items()).toEqual(['Image generation · 3 illustrations', 'Image generation · 1 icon']);
  });

  it('a row without a usable kind or count reads just "Image generation"', () => {
    render(<ToolActivityBar messages={[imageCall({}), imageCall({ kind: 'photo', count: 'three' })]} />);

    open();
    expect(items()).toEqual(['Image generation', 'Image generation']);
  });
});
