import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  EMPTY_V2_ASSEMBLY_RULES,
  V1_PROTECTED_IDENTITY,
  V2_PROTECTED_IDENTITY,
  syntheticDraftDefinitions,
  v2ProtectedStageView,
} from '../../../../tests/fixtures/mocks';
import type {
  AgentKey,
  AssemblyRulesV2,
  CustomTextBlock,
  ProtectedStageView,
} from '../../../api/agentDefinitions';
import { AssemblyEditor } from './AssemblyEditor';

const BLOCK_ONE = '11111111-1111-4111-8111-111111111111';
const BLOCK_TWO = '22222222-2222-4222-8222-222222222222';
const BLOCK_THREE = '33333333-3333-4333-8333-333333333333';

function callbacks() {
  return {
    onAddBlock: vi.fn(),
    onChangeText: vi.fn(),
    onChangeCondition: vi.fn(),
    onDeleteBlock: vi.fn(),
    onMoveBlock: vi.fn(),
  };
}

function v1View(agentKey: AgentKey): ProtectedStageView[] {
  return structuredClone(syntheticDraftDefinitions[agentKey].protected_stage_view);
}

function renderEditor(options: {
  agentKey: AgentKey;
  view: ProtectedStageView[];
  rules: AssemblyRulesV2 | null;
  disabled?: boolean;
}) {
  const handlers = callbacks();
  const identity = options.rules === null ? V1_PROTECTED_IDENTITY : V2_PROTECTED_IDENTITY;
  const view = render(
    <AssemblyEditor
      agentKey={options.agentKey}
      protectedStageView={options.view}
      rules={options.rules}
      protectedAssembly={structuredClone(identity)}
      disabled={options.disabled ?? false}
      {...handlers}
    />,
  );
  return { ...view, handlers };
}

function groupLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[role="group"]')]
    .map((group) => group.getAttribute('aria-label') ?? '');
}

function protectedRow(label: string): HTMLElement {
  return screen.getByRole('group', { name: `Protected stage: ${label}` });
}

function displayText(label: string): string {
  return protectedRow(label).querySelector('pre')?.textContent ?? '';
}

function customBlock(id: string, text: string, anchor: CustomTextBlock['anchor']): CustomTextBlock {
  return { kind: 'custom_text', block_id: id, anchor, condition: 'always', text };
}

describe('AssemblyEditor protected rows', () => {
  it('renders every required Graph Version 1 protected row with exact locked values', () => {
    const { container } = renderEditor({
      agentKey: 'architect',
      view: v1View('architect'),
      rules: null,
    });

    expect(groupLabels(container)).toEqual([
      'Protected assembly identity',
      'Authored prompt stage',
      'Protected stage: Slide frame constraints',
      'Protected stage: Design system precedence',
      'Protected stage: Graph Version 1 runtime payload',
      'Protected stage: Structured-output binding',
    ]);
    expect(displayText('Slide frame constraints')).toBe('Synthetic v1 slide frame constraints text.');
    expect(displayText('Design system precedence')).toBe('Synthetic v1 design system precedence text.');
    expect(displayText('Graph Version 1 runtime payload')).toBe('json.dumps(payload, indent=2, default=str)');
    expect(displayText('Structured-output binding')).toBe('langchain.with_structured_output');

    const row = protectedRow('Slide frame constraints');
    expect(within(row).getByText('Slide frame constraints')).toBeVisible();
    // A server-owned stage label must not enter the heading tree, where it would
    // collide with the workbench's own "Graph Version 1" heading.
    expect(within(row).queryAllByRole('heading')).toEqual([]);
    expect(screen.queryAllByRole('heading', { name: /Graph Version 1/ })).toEqual([]);
    expect(within(row).getByText('Locked')).toBeVisible();
    expect(within(row).getByText('Design System inactive')).toBeVisible();
    expect(within(row).getByText('1')).toBeVisible();
    expect(within(row).getByText(V1_PROTECTED_IDENTITY.digest)).toBeVisible();
  });

  it('renders every required Graph Version 2 Build Reviewer row in exact server order', () => {
    const { container } = renderEditor({
      agentKey: 'build_reviewer',
      view: v2ProtectedStageView('build_reviewer'),
      rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES),
    });

    expect(groupLabels(container)).toEqual([
      'Protected assembly identity',
      'Authored prompt stage',
      'Custom blocks: After authored prompt',
      'Protected stage: Build Reviewer criteria',
      'Protected stage: Deck-brief re-review',
      'Custom blocks: After deck-brief re-review',
      'Protected stage: Slide frame constraints',
      'Protected stage: Design system precedence',
      'Custom blocks: After environment constraints',
      'Protected stage: Role-specific untrusted-data notice',
      'Protected stage: Untrusted-data opening delimiter',
      'Protected stage: Canonical runtime payload',
      'Protected stage: Untrusted-data closing delimiter',
      'Protected stage: Structured-output binding',
    ]);
    expect(displayText('Build Reviewer criteria')).toBe('Synthetic v2 Build Reviewer criteria text.');
    expect(displayText('Deck-brief re-review')).toBe('Synthetic v2 deck-brief re-review text.');
    expect(displayText('Role-specific untrusted-data notice'))
      .toBe('Synthetic v2 untrusted-data notice for build_reviewer.');
    expect(displayText('Untrusted-data opening delimiter')).toBe('<<<UNTRUSTED_DATA>>>');
    expect(displayText('Canonical runtime payload'))
      .toBe('json.dumps(payload, indent=2, default=str, sort_keys=True)');
    expect(displayText('Untrusted-data closing delimiter')).toBe('<<<END_UNTRUSTED_DATA>>>');
    expect(within(protectedRow('Deck-brief re-review')).getByText('Payload has a deck brief')).toBeVisible();
    expect(within(protectedRow('Design system precedence')).getByText('Design System active')).toBeVisible();
  });

  it.each([
    ['data_analyst' as AgentKey, null],
    ['data_analyst' as AgentKey, structuredClone(EMPTY_V2_ASSEMBLY_RULES)],
    ['build_reviewer' as AgentKey, structuredClone(EMPTY_V2_ASSEMBLY_RULES)],
  ])('every protected row of %s carries no editable control', (agentKey, rules) => {
    const view = rules === null ? v1View(agentKey) : v2ProtectedStageView(agentKey);
    renderEditor({ agentKey, view, rules });

    for (const row of view) {
      const element = protectedRow(row.label);
      expect(within(element).queryAllByRole('textbox')).toEqual([]);
      expect(within(element).queryAllByRole('button')).toEqual([]);
      expect(within(element).queryAllByRole('combobox')).toEqual([]);
      expect(within(element).queryAllByRole('listbox')).toEqual([]);
      expect(within(element).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
      expect(within(element).queryByRole('button', { name: 'Move up' })).not.toBeInTheDocument();
      expect(within(element).queryByRole('button', { name: 'Move down' })).not.toBeInTheDocument();
      expect(within(element).queryByRole('combobox', { name: 'Condition' })).not.toBeInTheDocument();
    }
  });

  it('offers no add, edit, delete, or reorder control while the role is still on v1', () => {
    renderEditor({ agentKey: 'build_reviewer', view: v1View('build_reviewer'), rules: null });

    expect(screen.queryAllByRole('button')).toEqual([]);
    expect(screen.queryAllByRole('textbox')).toEqual([]);
    expect(screen.queryAllByRole('combobox')).toEqual([]);
    expect(screen.getByText('Custom text blocks require the Graph Version 2 protected assembly.'))
      .toBeVisible();
  });
});

describe('AssemblyEditor custom blocks', () => {
  it('offers the deck-brief anchor only for Build Reviewer', () => {
    const { container, unmount } = renderEditor({
      agentKey: 'architect',
      view: v2ProtectedStageView('architect'),
      rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES),
    });

    expect(groupLabels(container).filter((label) => label.startsWith('Custom blocks:'))).toEqual([
      'Custom blocks: After authored prompt',
      'Custom blocks: After environment constraints',
    ]);
    expect(screen.getByRole('button', { name: 'Add custom block After authored prompt' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Add custom block After environment constraints' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Add custom block After deck-brief re-review' }))
      .not.toBeInTheDocument();
    unmount();

    const reviewer = renderEditor({
      agentKey: 'build_reviewer',
      view: v2ProtectedStageView('build_reviewer'),
      rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES),
    });
    expect(groupLabels(reviewer.container).filter((label) => label.startsWith('Custom blocks:'))).toEqual([
      'Custom blocks: After authored prompt',
      'Custom blocks: After deck-brief re-review',
      'Custom blocks: After environment constraints',
    ]);
  });

  it('places every custom anchor before the payload and terminal rows', () => {
    const { container } = renderEditor({
      agentKey: 'build_reviewer',
      view: v2ProtectedStageView('build_reviewer'),
      rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES),
    });
    const labels = groupLabels(container);
    const payloadIndex = labels.indexOf('Protected stage: Canonical runtime payload');
    const terminalIndex = labels.indexOf('Protected stage: Structured-output binding');

    for (const [index, label] of labels.entries()) {
      if (!label.startsWith('Custom blocks:')) continue;
      expect(index).toBeLessThan(payloadIndex);
      expect(index).toBeLessThan(terminalIndex);
    }
    expect(labels.indexOf('Custom blocks: After environment constraints')).toBe(8);
  });

  it('renders siblings per anchor, withholds arrows at the edges, and targets the exact UUID', () => {
    const rules: AssemblyRulesV2 = {
      format_version: 2,
      custom_blocks: [
        customBlock(BLOCK_ONE, 'first authored sibling', 'after_authored_prompt'),
        customBlock(BLOCK_TWO, 'second authored sibling', 'after_authored_prompt'),
        customBlock(BLOCK_THREE, 'only environment sibling', 'after_environment_constraints'),
      ],
    };
    const { handlers } = renderEditor({
      agentKey: 'architect',
      view: v2ProtectedStageView('architect'),
      rules,
    });

    const authored = screen.getByRole('group', { name: 'Custom blocks: After authored prompt' });
    const first = within(authored).getByRole('group', { name: 'Custom block 1 at After authored prompt' });
    const second = within(authored).getByRole('group', { name: 'Custom block 2 at After authored prompt' });
    const lone = within(screen.getByRole('group', { name: 'Custom blocks: After environment constraints' }))
      .getByRole('group', { name: 'Custom block 1 at After environment constraints' });

    expect(within(first).getByRole('textbox', { name: 'Block text' })).toHaveValue('first authored sibling');
    expect(within(second).getByRole('textbox', { name: 'Block text' })).toHaveValue('second authored sibling');
    expect(within(lone).getByRole('textbox', { name: 'Block text' })).toHaveValue('only environment sibling');

    // An arrow can never cross an anchor: the first sibling has no Move up, the
    // last has no Move down, and a lone sibling has neither.
    expect(within(first).queryByRole('button', { name: 'Move up' })).not.toBeInTheDocument();
    expect(within(first).getByRole('button', { name: 'Move down' })).toBeEnabled();
    expect(within(second).getByRole('button', { name: 'Move up' })).toBeEnabled();
    expect(within(second).queryByRole('button', { name: 'Move down' })).not.toBeInTheDocument();
    expect(within(lone).queryByRole('button', { name: 'Move up' })).not.toBeInTheDocument();
    expect(within(lone).queryByRole('button', { name: 'Move down' })).not.toBeInTheDocument();

    fireEvent.change(within(second).getByRole('textbox', { name: 'Block text' }), {
      target: { value: 'edited second sibling' },
    });
    expect(handlers.onChangeText.mock.calls).toEqual([[BLOCK_TWO, 'edited second sibling']]);

    fireEvent.change(within(second).getByRole('combobox', { name: 'Condition' }), {
      target: { value: 'design_system_active' },
    });
    expect(handlers.onChangeCondition.mock.calls).toEqual([[BLOCK_TWO, 'design_system_active']]);

    fireEvent.click(within(first).getByRole('button', { name: 'Move down' }));
    expect(handlers.onMoveBlock.mock.calls).toEqual([[BLOCK_ONE, 'down']]);

    fireEvent.click(within(second).getByRole('button', { name: 'Move up' }));
    expect(handlers.onMoveBlock.mock.calls).toEqual([[BLOCK_ONE, 'down'], [BLOCK_TWO, 'up']]);

    fireEvent.click(within(lone).getByRole('button', { name: 'Delete' }));
    expect(handlers.onDeleteBlock.mock.calls).toEqual([[BLOCK_THREE]]);

    fireEvent.click(screen.getByRole('button', { name: 'Add custom block After environment constraints' }));
    expect(handlers.onAddBlock.mock.calls).toEqual([['after_environment_constraints']]);
  });

  it('exposes every condition literal exactly once and never an anchor control', () => {
    renderEditor({
      agentKey: 'architect',
      view: v2ProtectedStageView('architect'),
      rules: {
        format_version: 2,
        custom_blocks: [customBlock(BLOCK_ONE, 'text', 'after_authored_prompt')],
      },
    });

    const condition = screen.getByRole('combobox', { name: 'Condition' });
    expect([...condition.querySelectorAll('option')].map((option) => option.getAttribute('value')))
      .toEqual([
        'always', 'design_system_active', 'design_system_inactive', 'payload_has_deck_brief',
      ]);
    expect(screen.queryByRole('combobox', { name: 'Anchor' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('combobox')).toHaveLength(1);
  });

  it('disables every custom control while an operation is pending', () => {
    renderEditor({
      agentKey: 'architect',
      view: v2ProtectedStageView('architect'),
      rules: {
        format_version: 2,
        custom_blocks: [
          customBlock(BLOCK_ONE, 'a', 'after_authored_prompt'),
          customBlock(BLOCK_TWO, 'b', 'after_authored_prompt'),
        ],
      },
      disabled: true,
    });

    for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled();
    for (const textbox of screen.getAllByRole('textbox')) expect(textbox).toBeDisabled();
    for (const combobox of screen.getAllByRole('combobox')) expect(combobox).toBeDisabled();
  });
});
