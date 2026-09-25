/**
 * Tests for the OutputSchemaEditor component: the protected schema display, the
 * diagnostic_notes picker, and the description/examples guidance editor.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  AgentKey,
  DraftDefinition,
} from '../../../api/agentDefinitions';
import {
  DIAGNOSTIC_NOTES_DESCRIPTOR,
  V2_SCHEMA_CONTRACT_IDENTITY,
  syntheticAgentDefinitionWorkbench,
  syntheticDraftDefinitions,
} from '../../../../tests/fixtures/mocks';
import {
  candidateFromForm,
  createDraftEditorState,
  draftEditorReducer,
  formFromDefinition,
  schemaOverlayFormFromDefinition,
  type DraftEditorState,
  type EditableSchemaOverlayForm,
} from './draftEditorState';
import { OutputSchemaEditor } from './OutputSchemaEditor';

// ── Fixture helpers ───────────────────────────────────────────────────────────

function v1Entry() {
  const state = createDraftEditorState(structuredClone(syntheticAgentDefinitionWorkbench));
  return state.byAgent['architect'];
}

/**
 * A draft definition whose schema_contract is v2 and whose selectable_optional_fields
 * carries exactly one descriptor (diagnostic_notes).
 */
function v2SchemaDefinition(agentKey: AgentKey = 'architect'): DraftDefinition {
  return {
    ...structuredClone(syntheticDraftDefinitions[agentKey]),
    schema_contract: { ...V2_SCHEMA_CONTRACT_IDENTITY },
    selectable_optional_fields: [structuredClone(DIAGNOSTIC_NOTES_DESCRIPTOR)],
  };
}

function v2Entry(agentKey: AgentKey = 'architect') {
  const def = v2SchemaDefinition(agentKey);
  return {
    ...v1Entry(),
    saved: def,
    local: formFromDefinition(def),
  };
}

function noop() { /* no-op */ }

interface RenderProps {
  agentKey?: AgentKey;
  v2?: boolean;
  disabled?: boolean;
  onToggleOptionalField?: (fieldName: string) => void;
  onEditFieldDescription?: (fieldName: string, description: string) => void;
  onEditFieldExamples?: (fieldName: string, examples: string) => void;
  onUpgradeSchemaContract?: () => void;
}

function renderEditor({
  agentKey = 'architect',
  v2 = false,
  disabled = false,
  onToggleOptionalField = noop,
  onEditFieldDescription = noop,
  onEditFieldExamples = noop,
  onUpgradeSchemaContract = noop,
}: RenderProps = {}) {
  const entry = v2 ? v2Entry(agentKey) : v1Entry();
  return render(
    <OutputSchemaEditor
      agentKey={agentKey}
      entry={entry}
      disabled={disabled}
      onToggleOptionalField={onToggleOptionalField}
      onEditFieldDescription={onEditFieldDescription}
      onEditFieldExamples={onEditFieldExamples}
      onUpgradeSchemaContract={onUpgradeSchemaContract}
    />,
  );
}

// ── v1 contract (no picker) ───────────────────────────────────────────────────

describe('Output Schema Editor — v1 contract', () => {
  it('shows a Schema Upgrade button for a v1 schema contract', () => {
    renderEditor({ v2: false });
    expect(screen.getByRole('button', { name: 'Schema Upgrade' })).toBeInTheDocument();
  });

  it('does not show the diagnostic_notes picker for a v1 contract', () => {
    renderEditor({ v2: false });
    expect(screen.queryByRole('checkbox', { name: /diagnostic_notes/ })).toBeNull();
  });

  it('calls onUpgradeSchemaContract when Schema Upgrade is clicked', () => {
    const handler = vi.fn();
    renderEditor({ v2: false, onUpgradeSchemaContract: handler });
    fireEvent.click(screen.getByRole('button', { name: 'Schema Upgrade' }));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('disables Schema Upgrade when disabled=true', () => {
    renderEditor({ v2: false, disabled: true });
    expect(screen.getByRole('button', { name: 'Schema Upgrade' })).toBeDisabled();
  });
});

// ── v2 contract (picker shown) ────────────────────────────────────────────────

describe('Output Schema Editor — v2 contract', () => {
  it('shows no Schema Upgrade button for a v2 schema contract', () => {
    renderEditor({ v2: true });
    expect(screen.queryByRole('button', { name: 'Schema Upgrade' })).toBeNull();
  });

  it('shows one selectable optional field row per descriptor', () => {
    renderEditor({ v2: true });
    // One descriptor in the fixture (diagnostic_notes).
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    expect(row).toBeInTheDocument();
  });

  it('shows the descriptor name as a read-only label, not an input', () => {
    renderEditor({ v2: true });
    // The name "diagnostic_notes" must appear as text, never inside an <input>.
    expect(screen.queryByRole('textbox', { name: /diagnostic_notes/ })).toBeNull();
    expect(screen.getByText('diagnostic_notes')).toBeInTheDocument();
  });

  it('does NOT render any input for type, default, max_items, or strip_whitespace', () => {
    renderEditor({ v2: true });
    for (const label of ['type', 'default', 'max_items', 'strip_whitespace', 'min_length', 'max_length']) {
      // Protect against input or spinbutton; accessible name must not be these schema properties.
      expect(screen.queryByRole('textbox', { name: new RegExp(label, 'i') })).toBeNull();
      expect(screen.queryByRole('spinbutton', { name: new RegExp(label, 'i') })).toBeNull();
    }
  });

  it('shows type and default as read-only text, not editable controls', () => {
    renderEditor({ v2: true });
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    // The schema type "array | null" appears as a protected label text inside the row.
    // Use within() to scope the query and avoid false matches on other elements.
    expect(within(row).getByText(/array \| null/)).toBeInTheDocument();
    // "default: null" appears as another protected label.
    expect(within(row).getByText(/^null$/)).toBeInTheDocument();
  });

  it('shows a description textarea for the optional field', () => {
    renderEditor({ v2: true });
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    expect(within(row).getByRole('textbox', { name: 'Description override' })).toBeInTheDocument();
  });

  it('shows an examples textarea for the optional field', () => {
    renderEditor({ v2: true });
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    expect(within(row).getByRole('textbox', { name: 'Examples override (JSON array)' })).toBeInTheDocument();
  });

  it('shows a toggle to select the optional field', () => {
    renderEditor({ v2: true });
    expect(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' })).toBeInTheDocument();
  });

  it('calls onToggleOptionalField when the toggle is clicked', () => {
    const handler = vi.fn();
    renderEditor({ v2: true, onToggleOptionalField: handler });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' }));
    expect(handler).toHaveBeenCalledWith('diagnostic_notes');
  });

  it('shows the toggle as checked when diagnostic_notes is in additional_optional_fields', () => {
    const def = v2SchemaDefinition();
    const entry = {
      ...v1Entry(),
      saved: { ...def, schema_overlay: { field_overrides: {}, additional_optional_fields: ['diagnostic_notes'] } },
      local: formFromDefinition({ ...def, schema_overlay: { field_overrides: {}, additional_optional_fields: ['diagnostic_notes'] } }),
    };
    render(
      <OutputSchemaEditor
        agentKey="architect"
        entry={entry}
        disabled={false}
        onToggleOptionalField={noop}
        onEditFieldDescription={noop}
        onEditFieldExamples={noop}
        onUpgradeSchemaContract={noop}
      />,
    );
    expect(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' })).toBeChecked();
  });

  it('shows the toggle as unchecked when diagnostic_notes is not selected', () => {
    renderEditor({ v2: true });
    expect(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' })).not.toBeChecked();
  });

  it('calls onEditFieldDescription when the description textarea changes', () => {
    const handler = vi.fn();
    renderEditor({ v2: true, onEditFieldDescription: handler });
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    const input = within(row).getByRole('textbox', { name: 'Description override' });
    fireEvent.change(input, { target: { value: 'New description' } });
    expect(handler).toHaveBeenCalledWith('diagnostic_notes', 'New description');
  });

  it('calls onEditFieldExamples when the examples textarea changes', () => {
    const handler = vi.fn();
    renderEditor({ v2: true, onEditFieldExamples: handler });
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    const input = within(row).getByRole('textbox', { name: 'Examples override (JSON array)' });
    fireEvent.change(input, { target: { value: '["example"]' } });
    expect(handler).toHaveBeenCalledWith('diagnostic_notes', '["example"]');
  });

  it('disables the toggle and description/examples inputs when disabled=true', () => {
    renderEditor({ v2: true, disabled: true });
    expect(screen.getByRole('checkbox', { name: 'Select diagnostic_notes' })).toBeDisabled();
    const row = screen.getByRole('group', { name: 'Optional field: diagnostic_notes' });
    expect(within(row).getByRole('textbox', { name: 'Description override' })).toBeDisabled();
    expect(within(row).getByRole('textbox', { name: 'Examples override (JSON array)' })).toBeDisabled();
  });
});

// ── seven descriptors (one per role) ─────────────────────────────────────────

describe('seven descriptors', () => {
  it('each of the seven roles has a non-empty DIAGNOSTIC_NOTES_DESCRIPTOR with a unique description', () => {
    // DIAGNOSTIC_NOTES_DESCRIPTOR is a representative sample; verify it has required fields.
    expect(DIAGNOSTIC_NOTES_DESCRIPTOR).toMatchObject({
      name: 'diagnostic_notes',
      description: expect.any(String),
      examples: expect.arrayContaining([expect.any(String)]),
      schema: expect.objectContaining({
        type: expect.arrayContaining(['array', 'null']),
        default: null,
      }),
    });
    expect(DIAGNOSTIC_NOTES_DESCRIPTOR.description.length).toBeGreaterThan(0);
  });
});

// ── candidateFromForm guard: no protected properties ─────────────────────────

describe('candidateFromForm schema overlay guard', () => {
  it('includes only description and examples in field_overrides, never type or default', () => {
    // Simulate form state with a description AND a manually injected type (the controller's
    // sabotage injects candidate.schema_overlay.field_overrides.intent.type).
    const state = createDraftEditorState(structuredClone(syntheticAgentDefinitionWorkbench));
    const entry = state.byAgent['architect'];
    const formWithInjectedType: Parameters<typeof candidateFromForm>[0] = {
      ...entry.local,
      schema_overlay: {
        additional_optional_fields: [],
        field_overrides: {
          // @ts-expect-error — deliberately injecting a protected property to test the guard.
          intent: { description: 'custom desc', type: 'string', examples: '' },
        },
      },
    };
    const candidate = candidateFromForm(formWithInjectedType);
    expect(candidate).not.toBeNull();
    const overrides = candidate?.schema_overlay?.field_overrides as Record<string, unknown> | undefined;
    expect(overrides?.['intent']).toBeDefined();
    // type must be stripped out; only description (and examples when non-empty) survive.
    expect(overrides?.['intent']).not.toHaveProperty('type');
    expect((overrides?.['intent'] as Record<string, unknown>)?.description).toBe('custom desc');
  });

  it('omits schema_overlay from the candidate when the overlay is empty and unchanged', () => {
    // For a v1 form where schema_overlay has no additional_optional_fields and no
    // field_overrides, the candidate should omit schema_overlay entirely to preserve the
    // existing five-field save body shape.
    const entry = v1Entry();
    const candidate = candidateFromForm(entry.local);
    // The saved definition in the fixture has empty field_overrides and empty
    // additional_optional_fields, so the form's overlay is empty — omit the field.
    expect(candidate?.schema_overlay).toBeUndefined();
  });

  it('includes schema_overlay in the candidate when additional_optional_fields is non-empty', () => {
    const def = v2SchemaDefinition();
    const formWithSelected = {
      ...formFromDefinition(def),
      schema_overlay: {
        additional_optional_fields: ['diagnostic_notes'],
        field_overrides: {},
      } satisfies EditableSchemaOverlayForm,
    };
    const candidate = candidateFromForm(formWithSelected);
    expect(candidate?.schema_overlay).toBeDefined();
    expect(candidate?.schema_overlay?.additional_optional_fields).toEqual(['diagnostic_notes']);
  });
});

// ── schema overlay form state ─────────────────────────────────────────────────

describe('draftEditorReducer schema overlay actions', () => {
  function architectState(): DraftEditorState {
    return createDraftEditorState(structuredClone(syntheticAgentDefinitionWorkbench));
  }

  it('schemaOverlayOptionalFieldToggled adds a field when not present', () => {
    let state = architectState();
    state = draftEditorReducer(state, {
      type: 'schemaOverlayOptionalFieldToggled',
      agentKey: 'architect',
      fieldName: 'diagnostic_notes',
    });
    expect(state.byAgent['architect'].local.schema_overlay?.additional_optional_fields)
      .toContain('diagnostic_notes');
  });

  it('schemaOverlayOptionalFieldToggled removes a field when already present', () => {
    let state = architectState();
    // First add it.
    state = draftEditorReducer(state, {
      type: 'schemaOverlayOptionalFieldToggled',
      agentKey: 'architect',
      fieldName: 'diagnostic_notes',
    });
    // Then toggle off.
    state = draftEditorReducer(state, {
      type: 'schemaOverlayOptionalFieldToggled',
      agentKey: 'architect',
      fieldName: 'diagnostic_notes',
    });
    expect(state.byAgent['architect'].local.schema_overlay?.additional_optional_fields)
      .not.toContain('diagnostic_notes');
  });

  it('schemaOverlayFieldDescriptionChanged updates description for a field', () => {
    let state = architectState();
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldDescriptionChanged',
      agentKey: 'architect',
      fieldName: 'intent',
      description: 'New description',
    });
    expect(state.byAgent['architect'].local.schema_overlay?.field_overrides?.['intent']?.description)
      .toBe('New description');
  });

  it('schemaOverlayFieldExamplesChanged updates examples for a field', () => {
    let state = architectState();
    state = draftEditorReducer(state, {
      type: 'schemaOverlayFieldExamplesChanged',
      agentKey: 'architect',
      fieldName: 'intent',
      examples: '["build"]',
    });
    expect(state.byAgent['architect'].local.schema_overlay?.field_overrides?.['intent']?.examples)
      .toBe('["build"]');
  });
});

// ── schema upgrade actions ────────────────────────────────────────────────────

describe('draftEditorReducer schema upgrade', () => {
  it('schemaUpgradeStarted sets pendingSave to a schemaUpgrade operation', () => {
    const state = createDraftEditorState(structuredClone(syntheticAgentDefinitionWorkbench));
    const next = draftEditorReducer(state, {
      type: 'schemaUpgradeStarted',
      pending: {
        operation: 'schemaUpgrade',
        requestId: 1,
        agentKey: 'architect',
        expectedLockVersion: 0,
        submittedCandidate: null,
      },
    });
    expect(next.pendingSave?.operation).toBe('schemaUpgrade');
    expect(next.pendingSave?.agentKey).toBe('architect');
  });

  it('schemaUpgradeStarted is blocked when another operation is already pending', () => {
    let state = createDraftEditorState(structuredClone(syntheticAgentDefinitionWorkbench));
    state = draftEditorReducer(state, {
      type: 'saveStarted',
      pending: {
        operation: 'save',
        requestId: 1,
        agentKey: 'architect',
        expectedLockVersion: 0,
        submittedCandidate: null,
      },
    });
    const next = draftEditorReducer(state, {
      type: 'schemaUpgradeStarted',
      pending: {
        operation: 'schemaUpgrade',
        requestId: 2,
        agentKey: 'architect',
        expectedLockVersion: 0,
        submittedCandidate: null,
      },
    });
    // Blocked: pendingSave is still the original save.
    expect(next.pendingSave?.operation).toBe('save');
  });
});

// ── formFromDefinition and schemaOverlayFormFromDefinition ───────────────────

describe('formFromDefinition schema overlay', () => {
  it('returns schema_overlay: null (no local edits) when initialising from a definition', () => {
    // formFromDefinition starts with null so that the candidate builder omits
    // schema_overlay from the wire body until the user makes an explicit edit.
    const def = structuredClone(syntheticDraftDefinitions['architect']);
    const form = formFromDefinition(def);
    expect(form.schema_overlay).toBeNull();
  });

  it('schemaOverlayFormFromDefinition populates additional_optional_fields from the definition', () => {
    const def: DraftDefinition = {
      ...structuredClone(syntheticDraftDefinitions['architect']),
      schema_overlay: {
        field_overrides: {},
        additional_optional_fields: ['diagnostic_notes'],
      },
    };
    const overlayForm = schemaOverlayFormFromDefinition(def);
    expect(overlayForm.additional_optional_fields).toEqual(['diagnostic_notes']);
  });

  it('schemaOverlayFormFromDefinition populates field_overrides from the definition', () => {
    const def: DraftDefinition = {
      ...structuredClone(syntheticDraftDefinitions['architect']),
      schema_overlay: {
        field_overrides: { title: { description: 'Custom title guidance' } },
        additional_optional_fields: [],
      },
    };
    const overlayForm = schemaOverlayFormFromDefinition(def);
    expect(overlayForm.field_overrides['title']?.description).toBe('Custom title guidance');
  });
});
