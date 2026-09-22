import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import {
  AgentDefinitionApiError,
  getAgentDefinitionWorkbench,
} from '../../../api/agentDefinitions';
import type {
  AgentDefinitionWorkbenchResponse,
  AgentNode,
  ModelAgentNode,
} from '../../../api/agentDefinitions';

const DEFINITION_TABS = ['prompt', 'model', 'output-schema', 'assembly'] as const;
type DefinitionTab = (typeof DEFINITION_TABS)[number];

const TAB_LABELS: Record<DefinitionTab, string> = {
  prompt: 'Prompt',
  model: 'Model',
  'output-schema': 'Output Schema',
  assembly: 'Assembly',
};

function DefinitionTabContent({ node, tab }: { node: ModelAgentNode; tab: DefinitionTab }) {
  const definition = node.draft;

  if (tab === 'prompt') {
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-sm text-gray-800">
        {definition.prompt_text}
      </pre>
    );
  }
  if (tab === 'model') {
    return (
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-3 text-sm">
        <dt className="font-medium text-gray-600">Endpoint</dt><dd>{definition.model.endpoint_name}</dd>
        <dt className="font-medium text-gray-600">Temperature</dt><dd>{definition.model.temperature}</dd>
        <dt className="font-medium text-gray-600">Max tokens</dt><dd>{definition.model.max_tokens}</dd>
        <dt className="font-medium text-gray-600">Top P</dt><dd>{definition.model.top_p}</dd>
      </dl>
    );
  }
  if (tab === 'output-schema') {
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-sm text-gray-800">
        {JSON.stringify({
          schema_overlay: definition.schema_overlay,
          schema_contract: definition.schema_contract,
        }, null, 2)}
      </pre>
    );
  }
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-sm text-gray-800">
      {JSON.stringify({
        assembly_rules: definition.assembly_rules,
        protected_assembly: definition.protected_assembly,
      }, null, 2)}
    </pre>
  );
}

function DefinitionPanel({ node }: { node: ModelAgentNode }) {
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

  return (
    <>
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
              id={`${node.agent_key}-${tab}-tab`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`${node.agent_key}-${tab}-panel`}
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

      {DEFINITION_TABS.map((tab) => (
        <div
          key={tab}
          id={`${node.agent_key}-${tab}-panel`}
          role="tabpanel"
          aria-labelledby={`${node.agent_key}-${tab}-tab`}
          hidden={activeTab !== tab}
          className="min-h-72 rounded-md border border-gray-200 bg-gray-50 p-4"
        >
          <DefinitionTabContent node={node} tab={tab} />
        </div>
      ))}
    </>
  );
}

function WorkbenchContent({ workbench }: { workbench: AgentDefinitionWorkbenchResponse }) {
  const [selectedKey, setSelectedKey] = useState(workbench.nodes[0]?.agent_key);
  const selectedNode = workbench.nodes.find((node) => node.agent_key === selectedKey)
    ?? workbench.nodes[0];

  if (!selectedNode) {
    return <div role="alert">The Graph contains no nodes.</div>;
  }

  const selectNode = (node: AgentNode) => setSelectedKey(node.agent_key);

  return (
    <>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            Graph Version {workbench.active_release.version_number}
          </h2>
          <p className="mt-1 text-sm text-gray-500">Read-only Agent Definition browser</p>
        </div>
        <dl className="flex gap-5 text-sm text-gray-600">
          <div>
            <dt className="font-medium text-gray-500">Draft base</dt>
            <dd>Graph Version {workbench.draft.base_version_number}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-500">Lock version</dt>
            <dd>{workbench.draft.lock_version}</dd>
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
                return (
                  <button
                    key={node.agent_key}
                    type="button"
                    aria-current={selected ? 'true' : undefined}
                    onClick={() => selectNode(node)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                      selected ? 'bg-blue-50 font-medium text-blue-800' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {node.display_name}
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
            {selectedNode.execution_kind === 'deterministic' ? (
              <p className="rounded-md border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
                {selectedNode.read_only_reason}
              </p>
            ) : (
              <DefinitionPanel key={selectedNode.agent_key} node={selectedNode} />
            )}
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
