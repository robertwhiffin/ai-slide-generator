import { useRef, useState, type KeyboardEvent } from 'react';
import type {
  AgentKey,
  AssemblyCondition,
  CustomAnchor,
  DraftFieldError,
  ModelAgentNode,
} from '../../../api/agentDefinitions';
import { AssemblyEditor } from './AssemblyEditor';
import { OutputSchemaEditor } from './OutputSchemaEditor';
import {
  definitionFormatVersion,
  draftStatus,
  editableFormsEqual,
  formFromCandidate,
  formFromDefinition,
  isLegacyCompositeRole,
  type DraftEditorEntry,
  type EditableDraftField,
  type EditableModelDraftForm,
} from './draftEditorState';

const DEFINITION_TABS = ['prompt', 'model', 'output-schema', 'assembly'] as const;
type DefinitionTab = (typeof DEFINITION_TABS)[number];

const TAB_LABELS: Record<DefinitionTab, string> = {
  prompt: 'Prompt',
  model: 'Model',
  'output-schema': 'Output Schema',
  assembly: 'Assembly',
};

/** The exact upgrade-only code that requires manual prompt resolution. */
export const MANUAL_RESOLUTION_CODE = 'legacy_prompt_manual_resolution_required';

/** Every server issue is surfaced in its exact order; this only chooses the tab link. */
function issueTab(field: string): DefinitionTab {
  if (field === 'prompt_text' || field === 'candidate.prompt_text') return 'prompt';
  if (field.startsWith('candidate.schema_overlay') || field === 'schema_contract.version') {
    return 'output-schema';
  }
  return 'assembly';
}

interface DefinitionEditorProps {
  agentKey: AgentKey;
  node: ModelAgentNode;
  entry: DraftEditorEntry;
  saveDisabled: boolean;
  /** True while any Save, Upgrade, SourceRecovery, or SchemaUpgrade request is in flight. */
  operationsDisabled: boolean;
  /** True only while this affected v1 role's own Upgrade request is in flight. */
  promptDisabled: boolean;
  onEdit(agentKey: AgentKey, field: EditableDraftField, value: string): void;
  onSave(agentKey: AgentKey): Promise<void>;
  onUpgradeProtectedAssembly(agentKey: AgentKey): Promise<void>;
  onUpgradeSchemaContract(agentKey: AgentKey): Promise<void>;
  onToggleSchemaOverlayOptionalField(agentKey: AgentKey, fieldName: string): void;
  onEditSchemaOverlayFieldDescription(agentKey: AgentKey, fieldName: string, description: string): void;
  onEditSchemaOverlayFieldExamples(agentKey: AgentKey, fieldName: string, examples: string): void;
  onRestorePublishedV1Prompt(agentKey: AgentKey): Promise<void>;
  onAddAssemblyBlock(agentKey: AgentKey, anchor: CustomAnchor): void;
  onEditAssemblyBlockText(agentKey: AgentKey, blockId: string, text: string): void;
  onEditAssemblyBlockCondition(
    agentKey: AgentKey,
    blockId: string,
    condition: AssemblyCondition,
  ): void;
  onDeleteAssemblyBlock(agentKey: AgentKey, blockId: string): void;
  onMoveAssemblyBlock(agentKey: AgentKey, blockId: string, direction: 'up' | 'down'): void;
  onReloadServer(agentKey: AgentKey): void;
  onKeepLocal(agentKey: AgentKey): void;
  onRestoreSavedPrompt(agentKey: AgentKey): void;
  onRestoreRetained(agentKey: AgentKey, retainedId: string): void;
  onDiscardRetained(agentKey: AgentKey, retainedId: string): void;
}

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <span id={id} role="alert" className="mt-1 block text-xs text-red-700">{message}</span>
  ) : null;
}

function DraftValues({ label, values }: { label: string; values: EditableModelDraftForm }) {
  return (
    <div role="group" aria-label={label} className="rounded border border-current/20 bg-white/60 p-2">
      <h5 className="font-medium">{label}</h5>
      <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-2 text-xs">
        <dt>Prompt</dt><dd className="break-words font-mono">{values.prompt_text}</dd>
        <dt>Endpoint</dt><dd className="break-words font-mono">{values.endpoint_name}</dd>
        <dt>Temperature</dt><dd>{values.temperature}</dd>
        <dt>Maximum tokens</dt><dd>{values.max_tokens}</dd>
        <dt>Top-p</dt><dd>{values.top_p}</dd>
        {values.assembly_rules !== null && (
          <>
            <dt>Custom blocks</dt><dd>{values.assembly_rules.custom_blocks.length}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

export function DefinitionEditor({
  agentKey,
  node,
  entry,
  saveDisabled,
  operationsDisabled,
  promptDisabled,
  onEdit,
  onSave,
  onUpgradeProtectedAssembly,
  onUpgradeSchemaContract,
  onToggleSchemaOverlayOptionalField,
  onEditSchemaOverlayFieldDescription,
  onEditSchemaOverlayFieldExamples,
  onRestorePublishedV1Prompt,
  onAddAssemblyBlock,
  onEditAssemblyBlockText,
  onEditAssemblyBlockCondition,
  onDeleteAssemblyBlock,
  onMoveAssemblyBlock,
  onReloadServer,
  onKeepLocal,
  onRestoreSavedPrompt,
  onRestoreRetained,
  onDiscardRetained,
}: DefinitionEditorProps) {
  const [activeTab, setActiveTab] = useState<DefinitionTab>('prompt');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selectTab = (tab: DefinitionTab, focus = false) => {
    setActiveTab(tab);
    if (focus) {
      const index = DEFINITION_TABS.indexOf(tab);
      queueMicrotask(() => tabRefs.current[index]?.focus());
    }
  };

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % DEFINITION_TABS.length;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + DEFINITION_TABS.length) % DEFINITION_TABS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = DEFINITION_TABS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(DEFINITION_TABS[nextIndex], true);
  };

  const conflictServer = entry.conflict
    ? formFromDefinition(entry.conflict.server.definitions[agentKey])
    : null;
  const conflictSubmitted = entry.conflict && entry.conflict.client_candidate !== null
    ? formFromCandidate(entry.conflict.client_candidate)
    : null;
  const currentDiffersFromSubmitted = conflictSubmitted !== null
    && !editableFormsEqual(entry.local, conflictSubmitted);

  const savedFormatVersion = definitionFormatVersion(entry.saved);
  const legacyRole = isLegacyCompositeRole(agentKey) && savedFormatVersion === 1;
  const promptDirty = entry.local.prompt_text !== entry.saved.prompt_text;
  const manualResolutionRequired = entry.responseIssues.some(
    (issue) => issue.code === MANUAL_RESOLUTION_CODE,
  );

  const issueList = (issues: DraftFieldError[]) => (
    <section
      role="region"
      aria-labelledby={`${agentKey}-issues-heading`}
      className="mb-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
    >
      <h4 id={`${agentKey}-issues-heading`} className="font-semibold">Server rejected this request</h4>
      <ol className="mt-2 space-y-2">
        {issues.map((issue) => (
          <li key={`${issue.field}:${issue.code}`}>
            <p className="font-mono text-xs">{`${issue.field} — ${issue.code}`}</p>
            <p>{issue.message}</p>
            <button type="button" onClick={() => selectTab(issueTab(issue.field), true)}>
              {`Go to ${TAB_LABELS[issueTab(issue.field)]} tab`}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );

  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span role="status" className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700">
          {draftStatus(entry)}
        </span>
        <button
          type="button"
          disabled={saveDisabled || entry.conflict !== null}
          onClick={() => { void onSave(agentKey); }}
          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          Save Draft
        </button>
      </div>

      {entry.requestError && (
        <div role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {entry.requestError}
        </div>
      )}
      {entry.responseIssues.length > 0 && issueList(entry.responseIssues)}
      {entry.conflict && (
        <section
          role="region"
          aria-labelledby={`${agentKey}-conflict-heading`}
          className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <h4 id={`${agentKey}-conflict-heading`} className="font-semibold">Draft changed on the server</h4>
          <p className="mt-1">
            Expected lock {entry.conflict.expected_lock_version}; Current lock {entry.conflict.current_lock_version}
          </p>
          <div className="mt-2 grid gap-2">
            {conflictServer && <DraftValues label="Server values" values={conflictServer} />}
            {conflictSubmitted && <DraftValues label="Submitted values" values={conflictSubmitted} />}
            {currentDiffersFromSubmitted && <DraftValues label="Current local values" values={entry.local} />}
          </div>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => onReloadServer(agentKey)}>Reload server</button>
            <button type="button" onClick={() => onKeepLocal(agentKey)}>Keep local</button>
          </div>
        </section>
      )}
      {entry.retainedForms.length > 0 && (
        <section
          role="region"
          aria-labelledby={`${agentKey}-recovery-heading`}
          className="mb-3 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"
        >
          <h4 id={`${agentKey}-recovery-heading`} className="font-semibold">Values retained for recovery</h4>
          <ol className="mt-2 space-y-3">
            {entry.retainedForms.map((retained, index) => (
              <li
                key={retained.id}
                role="group"
                // Distinct from the inner values group's name. A nested pair whose names
                // are prefix-related resolves to two elements in any name-substring
                // query, which is the same collision class as the stage-label heading.
                aria-label={`Retained alternative ${index + 1}`}
                data-retained-id={retained.id}
              >
                <p className="text-xs">{retained.reason}</p>
                <div className="mt-1">
                  <DraftValues label={`Retained values ${index + 1}`} values={retained.form} />
                </div>
                <label
                  htmlFor={`${agentKey}-${retained.id}-manual`}
                  className="mt-2 block text-xs font-medium"
                >
                  Manual-only prompt bytes
                </label>
                <textarea
                  id={`${agentKey}-${retained.id}-manual`}
                  readOnly
                  aria-readonly="true"
                  value={retained.manualOnlyPrompt}
                  className="mt-1 min-h-16 w-full rounded border border-blue-300 p-2 font-mono text-xs"
                />
                <div className="mt-2 flex gap-2">
                  <button type="button" onClick={() => onRestoreRetained(agentKey, retained.id)}>
                    Restore retained values
                  </button>
                  <button type="button" onClick={() => onDiscardRetained(agentKey, retained.id)}>
                    Discard retained values
                  </button>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <div
        role="tablist"
        aria-label={`${node.display_name} definition`}
        className="mb-4 flex border-b border-gray-200"
      >
        {DEFINITION_TABS.map((tab, index) => {
          const selected = activeTab === tab;
          return (
            <button
              key={tab}
              ref={(element) => { tabRefs.current[index] = element; }}
              id={`${agentKey}-${tab}-tab`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${agentKey}-${tab}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => selectTab(tab)}
              onKeyDown={(event) => onTabKeyDown(event, index)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
                selected
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              {TAB_LABELS[tab]}
            </button>
          );
        })}
      </div>

      <div
        id={`${agentKey}-prompt-panel`}
        role="tabpanel"
        aria-labelledby={`${agentKey}-prompt-tab`}
        hidden={activeTab !== 'prompt'}
        className="min-h-72 rounded-md border border-gray-200 bg-gray-50 p-4"
      >
        <label htmlFor={`${agentKey}-prompt`} className="mb-2 block text-sm font-medium text-gray-700">
          Prompt text
        </label>
        <textarea
          id={`${agentKey}-prompt`}
          aria-describedby={entry.fieldErrors.prompt_text ? `${agentKey}-prompt-error` : undefined}
          value={entry.local.prompt_text}
          disabled={promptDisabled}
          onChange={(event) => onEdit(agentKey, 'prompt_text', event.currentTarget.value)}
          className="min-h-56 w-full rounded-md border border-gray-300 p-3 font-mono text-sm"
        />
        <FieldError id={`${agentKey}-prompt-error`} message={entry.fieldErrors.prompt_text} />
        {legacyRole && promptDirty && (
          <button type="button" onClick={() => onRestoreSavedPrompt(agentKey)} className="mt-2">
            Restore saved prompt
          </button>
        )}
        {legacyRole && manualResolutionRequired && (
          <button
            type="button"
            disabled={operationsDisabled}
            onClick={() => { void onRestorePublishedV1Prompt(agentKey); }}
            className="mt-2 block"
          >
            Restore published Graph Version 1 prompt
          </button>
        )}
      </div>

      <div
        id={`${agentKey}-model-panel`}
        role="tabpanel"
        aria-labelledby={`${agentKey}-model-tab`}
        hidden={activeTab !== 'model'}
        className="min-h-72 space-y-3 rounded-md border border-gray-200 bg-gray-50 p-4"
      >
        <div>
          <label htmlFor={`${agentKey}-endpoint`} className="block text-sm font-medium text-gray-700">Endpoint</label>
          <input
            id={`${agentKey}-endpoint`}
            aria-describedby={entry.fieldErrors.endpoint_name ? `${agentKey}-endpoint-error` : undefined}
            type="text"
            value={entry.local.endpoint_name}
            onChange={(event) => onEdit(agentKey, 'endpoint_name', event.currentTarget.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 p-2 font-normal"
          />
          <FieldError id={`${agentKey}-endpoint-error`} message={entry.fieldErrors.endpoint_name} />
        </div>
        <div>
          <label htmlFor={`${agentKey}-temperature`} className="block text-sm font-medium text-gray-700">Temperature</label>
          <input
            id={`${agentKey}-temperature`}
            aria-describedby={entry.fieldErrors.temperature ? `${agentKey}-temperature-error` : undefined}
            type="number"
            step="any"
            value={entry.local.temperature}
            onChange={(event) => onEdit(agentKey, 'temperature', event.currentTarget.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 p-2 font-normal"
          />
          <FieldError id={`${agentKey}-temperature-error`} message={entry.fieldErrors.temperature} />
        </div>
        <div>
          <label htmlFor={`${agentKey}-max-tokens`} className="block text-sm font-medium text-gray-700">Maximum tokens</label>
          <input
            id={`${agentKey}-max-tokens`}
            aria-describedby={entry.fieldErrors.max_tokens ? `${agentKey}-max-tokens-error` : undefined}
            type="number"
            step="1"
            value={entry.local.max_tokens}
            onChange={(event) => onEdit(agentKey, 'max_tokens', event.currentTarget.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 p-2 font-normal"
          />
          <FieldError id={`${agentKey}-max-tokens-error`} message={entry.fieldErrors.max_tokens} />
        </div>
        <div>
          <label htmlFor={`${agentKey}-top-p`} className="block text-sm font-medium text-gray-700">Top-p</label>
          <input
            id={`${agentKey}-top-p`}
            aria-describedby={entry.fieldErrors.top_p ? `${agentKey}-top-p-error` : undefined}
            type="number"
            step="any"
            value={entry.local.top_p}
            onChange={(event) => onEdit(agentKey, 'top_p', event.currentTarget.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 p-2 font-normal"
          />
          <FieldError id={`${agentKey}-top-p-error`} message={entry.fieldErrors.top_p} />
        </div>
      </div>

      <div
        id={`${agentKey}-output-schema-panel`}
        role="tabpanel"
        aria-labelledby={`${agentKey}-output-schema-tab`}
        hidden={activeTab !== 'output-schema'}
        className="min-h-72 rounded-md border border-gray-200 bg-gray-50 p-4"
      >
        <OutputSchemaEditor
          agentKey={agentKey}
          entry={entry}
          disabled={operationsDisabled}
          onToggleOptionalField={(fieldName) => onToggleSchemaOverlayOptionalField(agentKey, fieldName)}
          onEditFieldDescription={(fieldName, desc) => onEditSchemaOverlayFieldDescription(agentKey, fieldName, desc)}
          onEditFieldExamples={(fieldName, examples) => onEditSchemaOverlayFieldExamples(agentKey, fieldName, examples)}
          onUpgradeSchemaContract={() => { void onUpgradeSchemaContract(agentKey); }}
        />
      </div>

      <div
        id={`${agentKey}-assembly-panel`}
        role="tabpanel"
        aria-labelledby={`${agentKey}-assembly-tab`}
        hidden={activeTab !== 'assembly'}
        className="min-h-72 space-y-3 rounded-md border border-gray-200 bg-gray-50 p-4"
      >
        {savedFormatVersion === 1 && (
          <button
            type="button"
            disabled={operationsDisabled}
            onClick={() => { void onUpgradeProtectedAssembly(agentKey); }}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            Upgrade protected assembly
          </button>
        )}
        <AssemblyEditor
          agentKey={agentKey}
          protectedStageView={entry.saved.protected_stage_view}
          rules={entry.local.assembly_rules}
          protectedAssembly={entry.saved.protected_assembly}
          disabled={operationsDisabled}
          onAddBlock={(anchor) => onAddAssemblyBlock(agentKey, anchor)}
          onChangeText={(blockId, text) => onEditAssemblyBlockText(agentKey, blockId, text)}
          onChangeCondition={(blockId, condition) => onEditAssemblyBlockCondition(agentKey, blockId, condition)}
          onDeleteBlock={(blockId) => onDeleteAssemblyBlock(agentKey, blockId)}
          onMoveBlock={(blockId, direction) => onMoveAssemblyBlock(agentKey, blockId, direction)}
        />
      </div>
    </>
  );
}
