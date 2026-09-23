import { useEffect, useState } from 'react';
import {
  AgentDefinitionApiError,
  getAgentDefinitionWorkbench,
} from '../../../api/agentDefinitions';
import type {
  AgentDefinitionWorkbenchResponse,
  AgentNode,
} from '../../../api/agentDefinitions';
import { DefinitionEditor } from './DefinitionEditor';
import {
  definitionFormatVersion,
  draftStatus,
  isLegacyCompositeRole,
  validateDraftForm,
} from './draftEditorState';
import { useDraftEditor } from './useDraftEditor';

function WorkbenchContent({ workbench }: { workbench: AgentDefinitionWorkbenchResponse }) {
  const [selectedKey, setSelectedKey] = useState(workbench.nodes[0]?.agent_key);
  const editor = useDraftEditor(workbench);
  const selectedNode = workbench.nodes.find((node) => node.agent_key === selectedKey)
    ?? workbench.nodes[0];

  if (!selectedNode) return <div role="alert">The Graph contains no nodes.</div>;

  const selectNode = (node: AgentNode) => setSelectedKey(node.agent_key);

  return (
    <>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            Graph Version {workbench.active_release.version_number}
          </h2>
          <p className="mt-1 text-sm text-gray-500">Edit the shared Graph Draft explicitly</p>
        </div>
        <dl className="flex gap-5 text-sm text-gray-600">
          <div>
            <dt className="font-medium text-gray-500">Draft base</dt>
            <dd>Graph Version {editor.state.draft.base_version_number}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-500">Lock version</dt>
            <dd>{editor.state.draft.lock_version}</dd>
          </div>
        </dl>
      </header>

      <div data-testid="workbench-overflow" className="max-w-full overflow-x-auto pb-2">
        <div
          data-testid="workbench-grid"
          className="grid min-w-[1100px] grid-cols-[220px_minmax(520px,1fr)_260px] gap-4"
        >
          <nav aria-label="Graph nodes" className="rounded-lg border border-gray-200 bg-white p-3">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Graph nodes</h3>
            <div className="space-y-1">
              {workbench.nodes.map((node) => {
                const selected = node.agent_key === selectedNode.agent_key;
                const status = node.execution_kind === 'model'
                  ? draftStatus(editor.state.byAgent[node.agent_key])
                  : null;
                return (
                  <button
                    key={node.agent_key}
                    type="button"
                    aria-label={node.display_name}
                    aria-current={selected ? 'true' : undefined}
                    onClick={() => selectNode(node)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                      selected ? 'bg-blue-50 font-medium text-blue-800' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <span>{node.display_name}</span>
                    {status && <span className="mt-1 block text-xs font-normal text-gray-500">{status}</span>}
                  </button>
                );
              })}
            </div>
          </nav>

          <section data-testid="definition-pane" className="rounded-lg border border-gray-200 bg-white p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-gray-900">{selectedNode.display_name}</h3>
              <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">
                {selectedNode.execution_kind === 'model' ? 'Model agent' : 'Deterministic'}
              </span>
            </div>
            {selectedNode.execution_kind === 'deterministic' && (
              <p className="rounded-md border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
                {selectedNode.read_only_reason}
              </p>
            )}
            {workbench.nodes.filter((node) => node.execution_kind === 'model').map((node) => {
              if (node.execution_kind !== 'model') return null;
              const entry = editor.state.byAgent[node.agent_key];
              const pending = editor.state.pendingSave;
              // Every Save, Upgrade, and SourceRecovery button reads the same
              // aggregate pending slot; there is no second gate.
              const operationsDisabled = pending !== null;
              const promptDisabled = pending !== null
                && pending.operation === 'upgrade'
                && pending.agentKey === node.agent_key
                && isLegacyCompositeRole(node.agent_key)
                && definitionFormatVersion(entry.saved) === 1;
              return (
                <div key={node.agent_key} hidden={selectedNode.agent_key !== node.agent_key}>
                  <DefinitionEditor
                    agentKey={node.agent_key}
                    node={node}
                    entry={entry}
                    saveDisabled={operationsDisabled || !validateDraftForm(entry.local).ok}
                    operationsDisabled={operationsDisabled}
                    promptDisabled={promptDisabled}
                    onEdit={editor.edit}
                    onSave={editor.save}
                    onUpgradeProtectedAssembly={editor.upgradeProtectedAssembly}
                    onRestorePublishedV1Prompt={editor.restorePublishedV1Prompt}
                    onAddAssemblyBlock={editor.addAssemblyBlock}
                    onEditAssemblyBlockText={editor.editAssemblyBlockText}
                    onEditAssemblyBlockCondition={editor.editAssemblyBlockCondition}
                    onDeleteAssemblyBlock={editor.deleteAssemblyBlock}
                    onMoveAssemblyBlock={editor.moveAssemblyBlock}
                    onReloadServer={editor.reloadServer}
                    onKeepLocal={editor.keepLocal}
                    onRestoreSavedPrompt={editor.restoreSavedPrompt}
                    onRestoreRetained={editor.restoreRetained}
                    onDiscardRetained={editor.discardRetained}
                  />
                </div>
              );
            })}
          </section>

          <aside className="rounded-lg border border-gray-200 bg-white p-5" aria-label="Isolated testing">
            <h3 className="text-base font-semibold text-gray-900">Isolated testing</h3>
            <p className="mt-3 text-sm leading-6 text-gray-600">
              Isolated testing is not available in this release.
            </p>
          </aside>
        </div>
      </div>
    </>
  );
}

export function AgentDefinitionWorkbench() {
  const [workbench, setWorkbench] = useState<AgentDefinitionWorkbenchResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let active = true;
    getAgentDefinitionWorkbench().then(
      (response) => { if (active) setWorkbench(response); },
      (requestError: unknown) => { if (active) setError(requestError); },
    );
    return () => { active = false; };
  }, []);

  let content;
  if (error) {
    const status = error instanceof AgentDefinitionApiError ? error.status : 0;
    const detail = error instanceof AgentDefinitionApiError ? error.detail : 'Request failed';
    content = (
      <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        Unable to load Agent Definitions ({status}): {detail}
      </div>
    );
  } else if (!workbench) {
    content = <div role="status" className="p-6 text-sm text-gray-600">Loading Agent Definitions…</div>;
  } else {
    content = <WorkbenchContent workbench={workbench} />;
  }

  return (
    <div data-testid="agent-definition-workbench" className="min-w-0">
      {content}
    </div>
  );
}
