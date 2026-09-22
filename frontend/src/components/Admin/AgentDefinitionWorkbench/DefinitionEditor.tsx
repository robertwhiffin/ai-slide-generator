import { useRef, useState, type KeyboardEvent } from 'react';
import type { AgentKey, ModelAgentNode } from '../../../api/agentDefinitions';
import {
  draftStatus,
  editableFormsEqual,
  formFromCandidate,
  formFromDefinition,
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

interface DefinitionEditorProps {
  agentKey: AgentKey;
  node: ModelAgentNode;
  entry: DraftEditorEntry;
  saveDisabled: boolean;
  onEdit(agentKey: AgentKey, field: EditableDraftField, value: string): void;
  onSave(agentKey: AgentKey): Promise<void>;
  onReloadServer(agentKey: AgentKey): void;
  onKeepLocal(agentKey: AgentKey): void;
  onRestoreRecovery(agentKey: AgentKey): void;
  onDismissRecovery(agentKey: AgentKey): void;
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
      </dl>
    </div>
  );
}

export function DefinitionEditor({
  agentKey,
  node,
  entry,
  saveDisabled,
  onEdit,
  onSave,
  onReloadServer,
  onKeepLocal,
  onRestoreRecovery,
  onDismissRecovery,
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
  const conflictSubmitted = entry.conflict
    ? formFromCandidate(entry.conflict.client_candidate)
    : null;
  const currentDiffersFromSubmitted = conflictSubmitted !== null
    && !editableFormsEqual(entry.local, conflictSubmitted);

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
      {entry.recoveryForm && (
        <section
          role="region"
          aria-labelledby={`${agentKey}-recovery-heading`}
          className="mb-3 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"
        >
          <h4 id={`${agentKey}-recovery-heading`} className="font-semibold">Values retained for recovery</h4>
          <div className="mt-2"><DraftValues label="Retained values" values={entry.recoveryForm} /></div>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => onRestoreRecovery(agentKey)}>Restore retained values</button>
            <button type="button" onClick={() => onDismissRecovery(agentKey)}>Dismiss</button>
          </div>
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
          onChange={(event) => onEdit(agentKey, 'prompt_text', event.currentTarget.value)}
          className="min-h-56 w-full rounded-md border border-gray-300 p-3 font-mono text-sm"
        />
        <FieldError id={`${agentKey}-prompt-error`} message={entry.fieldErrors.prompt_text} />
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
        <pre className="whitespace-pre-wrap break-words font-mono text-sm text-gray-800">
          {JSON.stringify({
            schema_overlay: entry.saved.schema_overlay,
            schema_contract: entry.saved.schema_contract,
          }, null, 2)}
        </pre>
      </div>

      <div
        id={`${agentKey}-assembly-panel`}
        role="tabpanel"
        aria-labelledby={`${agentKey}-assembly-tab`}
        hidden={activeTab !== 'assembly'}
        className="min-h-72 rounded-md border border-gray-200 bg-gray-50 p-4"
      >
        <pre className="whitespace-pre-wrap break-words font-mono text-sm text-gray-800">
          {JSON.stringify({
            assembly_rules: entry.saved.assembly_rules,
            protected_assembly: entry.saved.protected_assembly,
          }, null, 2)}
        </pre>
      </div>
    </>
  );
}
