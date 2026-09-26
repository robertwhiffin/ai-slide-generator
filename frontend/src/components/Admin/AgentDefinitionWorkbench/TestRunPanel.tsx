import { useId, useState, type KeyboardEvent } from 'react';
import type {
  AgentKey,
  CreateTestCaseRequest,
  JsonValue,
  TestCaseListEntry,
  TestRunEvidence,
} from '../../../api/agentDefinitions';
import type { AgentTestingState, TestOperationKind } from './draftEditorState';

/** P7: a warning only, shown unconditionally; the server does not enforce it. */
export const SYNTHETIC_DATA_WARNING =
  'Synthetic data only: never enter real customer, personal or confidential data.';
/** P3: replacing a case is two actions, and the order matters. */
export const REPLACE_ORDER_HINT =
  'To replace a test case, add the new case first and then retire the old one: '
  + 'a role cannot lose its last required case.';
export const TEST_RUN_UNSAVED_HINT = "Save this role's edits before running a test case.";
const NO_RUN_YET = 'No run yet';
const BASELINE_NOT_RECORDED = 'Baseline not recorded';
const NOT_REPORTED = 'not reported';
const PAYLOAD_NOT_OBJECT = 'The synthetic payload must be a JSON object.';
const NAME_REQUIRED = 'Enter a test case name.';

const PENDING_TEXT: Record<TestOperationKind, string> = {
  testRun: 'Running the test case against the saved candidate…',
  baselineRun: 'Running the published baseline…',
  testCaseCreate: 'Saving the test case…',
  testCaseRetire: 'Retiring the test case…',
};

const VIEWS = ['Input', 'Compare', 'Checks'] as const;
type View = typeof VIEWS[number];

export interface TestRunPanelProps {
  agentKey: AgentKey;
  /** This role's panel state from the one reducer. */
  testing: AgentTestingState;
  /** The role's saved candidate hash, to mark evidence of an earlier candidate. */
  savedCandidateHash: string;
  /** True while any field of this role differs from its saved candidate. */
  candidateUnsaved: boolean;
  /** True while the one gate is held by any operation of any role. */
  operationsDisabled: boolean;
  /** This role's own pending test operation, or `null`. */
  pendingOperation: TestOperationKind | null;
  onLoadTestCases(agentKey: AgentKey): void;
  onRunTestCase(agentKey: AgentKey, testCaseId: number): void | Promise<void>;
  onRunPublishedBaseline(agentKey: AgentKey, testCaseId: number): void | Promise<void>;
  onCreateTestCase(agentKey: AgentKey, request: CreateTestCaseRequest): Promise<TestCaseListEntry | null>;
  onRetireTestCase(agentKey: AgentKey, testCaseId: number): void | Promise<void>;
}

/** Server evidence is only ever rendered as text: React escapes it, and nothing here parses markup. */
function jsonText(value: JsonValue): string {
  return JSON.stringify(value, null, 2);
}

function EvidenceBlock({ label, value }: { label: string; value: Record<string, JsonValue> | null }) {
  if (value === null) return null;
  return (
    <div>
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-2 text-xs text-gray-800">
        {jsonText(value)}
      </pre>
    </div>
  );
}

function usage(value: number | null, unit = ''): string {
  return value === null ? NOT_REPORTED : `${value}${unit}`;
}

function RunFacts({ evidence }: { evidence: TestRunEvidence }) {
  return (
    <ul className="space-y-0.5 text-xs text-gray-600">
      <li>Run {evidence.run_id} · Case version {evidence.test_case_version}</li>
      <li>Status: {evidence.execution_status}</li>
      {evidence.error_detail !== null && <li>Error: {evidence.error_detail}</li>}
      <li>Latency: {usage(evidence.latency_ms, ' ms')}</li>
      <li>Input tokens: {usage(evidence.input_tokens)}</li>
      <li>Output tokens: {usage(evidence.output_tokens)}</li>
      <li>By {evidence.run_by} at {evidence.run_at}</li>
    </ul>
  );
}

function CandidateEvidence({ evidence, savedCandidateHash }: {
  evidence: TestRunEvidence | null;
  savedCandidateHash: string;
}) {
  if (evidence === null) return <p className="text-gray-600">{NO_RUN_YET}</p>;
  const candidateRecorded = evidence.candidate_raw_output !== null || evidence.candidate_structured_output !== null;
  const baselineRecorded = evidence.baseline_raw_output !== null || evidence.baseline_structured_output !== null;
  return (
    <div className="space-y-3">
      <RunFacts evidence={evidence} />
      {evidence.candidate_hash !== savedCandidateHash && (
        <p className="text-xs text-amber-800">This run tested an earlier saved candidate.</p>
      )}
      {evidence.base_release_is_current === false && (
        <p className="text-xs text-amber-800">The published release changed after this run.</p>
      )}
      <div className="grid gap-3">
        <div>
          <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Candidate</h5>
          {candidateRecorded ? (
            <>
              <EvidenceBlock label="Structured output" value={evidence.candidate_structured_output} />
              <EvidenceBlock label="Raw output" value={evidence.candidate_raw_output} />
            </>
          ) : <p className="text-gray-600">No candidate output recorded.</p>}
        </div>
        <div>
          <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Published baseline (not approved)
          </h5>
          {baselineRecorded ? (
            <>
              <EvidenceBlock label="Structured output" value={evidence.baseline_structured_output} />
              <EvidenceBlock label="Raw output" value={evidence.baseline_raw_output} />
            </>
          ) : <p className="text-gray-600">{BASELINE_NOT_RECORDED}</p>}
        </div>
      </div>
    </div>
  );
}

function ChecksView({ evidence }: { evidence: TestRunEvidence | null }) {
  if (evidence === null) return <p className="text-gray-600">{NO_RUN_YET}</p>;
  return (
    <div className="space-y-2">
      <p className={evidence.deterministic_checks_passed ? 'text-green-800' : 'text-red-800'}>
        {evidence.deterministic_checks_passed ? 'Deterministic checks passed' : 'Deterministic checks failed'}
      </p>
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Deterministic checks</caption>
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">Result</th>
            <th scope="col">Message</th>
          </tr>
        </thead>
        <tbody>
          {evidence.deterministic_check_results.map((check) => (
            <tr
              key={check.name}
              data-check-state={check.passed ? 'passed' : 'failed'}
              className={check.passed ? '' : 'bg-red-50 text-red-900'}
            >
              <th scope="row" className="font-mono font-normal">{check.name}</th>
              <td>{check.passed ? 'Passed' : 'Failed'}</td>
              <td>
                {check.message ?? '—'}
                {check.issues.length > 0 && (
                  <ul>
                    {check.issues.map((issue, index) => (
                      <li key={`${issue.code}-${index}`}>
                        {issue.field === null ? issue.code : `${issue.code} (${issue.field})`}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function parsePayload(text: string): Record<string, JsonValue> | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      ? value as Record<string, JsonValue>
      : null;
  } catch {
    return null;
  }
}

function AddTestCaseForm({ agentKey, disabled, onCreate, onClose }: {
  agentKey: AgentKey;
  disabled: boolean;
  onCreate(request: CreateTestCaseRequest): Promise<TestCaseListEntry | null>;
  onClose(created: TestCaseListEntry | null): void;
}) {
  const id = useId();
  const [name, setName] = useState('');
  const [payloadText, setPayloadText] = useState('{}');
  const [isRequired, setIsRequired] = useState(false);
  const [designSystemActive, setDesignSystemActive] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async () => {
    if (disabled) return;
    if (!name.trim()) {
      setFormError(NAME_REQUIRED);
      return;
    }
    const payload = parsePayload(payloadText);
    if (payload === null) {
      setFormError(PAYLOAD_NOT_OBJECT);
      return;
    }
    setFormError(null);
    const created = await onCreate({
      agent_key: agentKey,
      name: name.trim(),
      synthetic_payload: payload,
      assembly_context: { design_system_active: designSystemActive },
      is_required: isRequired,
    });
    if (created !== null) onClose(created);
  };

  return (
    <div className="space-y-2 rounded-md border border-gray-200 p-3">
      <div>
        <label htmlFor={`${id}-name`} className="block text-xs font-medium text-gray-700">Test case name</label>
        <input
          id={`${id}-name`}
          type="text"
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          className="mt-1 block w-full rounded-md border border-gray-300 p-1 text-xs"
        />
      </div>
      <div>
        <label htmlFor={`${id}-payload`} className="block text-xs font-medium text-gray-700">
          Synthetic payload (JSON)
        </label>
        <textarea
          id={`${id}-payload`}
          aria-describedby={`${id}-warning${formError ? ` ${id}-error` : ''}`}
          value={payloadText}
          onChange={(event) => setPayloadText(event.currentTarget.value)}
          rows={5}
          className="mt-1 block w-full rounded-md border border-gray-300 p-1 font-mono text-xs"
        />
        <p id={`${id}-warning`} className="mt-1 text-xs font-medium text-amber-800">{SYNTHETIC_DATA_WARNING}</p>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={isRequired} onChange={(event) => setIsRequired(event.currentTarget.checked)} />
        Required test case
      </label>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={designSystemActive}
          onChange={(event) => setDesignSystemActive(event.currentTarget.checked)}
        />
        Design system active
      </label>
      {formError && <p id={`${id}-error`} role="alert" className="text-xs text-red-700">{formError}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={disabled} onClick={() => { void submit(); }} className="rounded-md border border-gray-300 px-2 py-1 text-xs disabled:text-gray-400">
          Save test case
        </button>
        <button type="button" onClick={() => onClose(null)} className="rounded-md px-2 py-1 text-xs">
          Cancel
        </button>
      </div>
    </div>
  );
}

/**
 * The right-pane Agent Test Case panel for one model role (#267): the case selector,
 * the Input / Compare / Checks views of its evidence, and the explicit run and case
 * controls. Every operation goes through the workbench's one gate; this component
 * holds only view state (the selected case, the open view and the add form).
 */
export function TestRunPanel({
  agentKey,
  testing,
  savedCandidateHash,
  candidateUnsaved,
  operationsDisabled,
  pendingOperation,
  onLoadTestCases,
  onRunTestCase,
  onRunPublishedBaseline,
  onCreateTestCase,
  onRetireTestCase,
}: TestRunPanelProps) {
  const id = useId();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [view, setView] = useState<View>('Input');
  const [adding, setAdding] = useState(false);
  const [confirmingRetire, setConfirmingRetire] = useState(false);

  const selected = testing.cases.find((item) => item.id === selectedId) ?? testing.cases[0] ?? null;
  const candidateEvidence = selected !== null && testing.candidateEvidence?.test_case_id === selected.id
    ? testing.candidateEvidence
    : null;
  const baselineEvidence = selected !== null && testing.baselineEvidence?.test_case_id === selected.id
    ? testing.baselineEvidence
    : null;
  const loaded = testing.casesStatus === 'ready'
    || (testing.casesStatus === 'loading' && testing.cases.length > 0);

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = VIEWS.indexOf(view);
    if (event.key === 'ArrowRight') setView(VIEWS[(index + 1) % VIEWS.length]);
    if (event.key === 'ArrowLeft') setView(VIEWS[(index + VIEWS.length - 1) % VIEWS.length]);
  };

  return (
    <div className="mt-3 space-y-3 text-sm">
      <p className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs font-medium text-amber-900">
        {SYNTHETIC_DATA_WARNING}
      </p>
      {testing.error && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {testing.error}
        </div>
      )}
      {testing.issues.length > 0 && (
        <ul aria-label="Test case issues" className="list-disc pl-4 text-xs text-red-800">
          {testing.issues.map((issue, index) => (
            <li key={`${issue.field}-${issue.code}-${index}`}>{`${issue.field}: ${issue.message}`}</li>
          ))}
        </ul>
      )}
      {pendingOperation !== null && (
        <p aria-live="polite" className="text-xs text-gray-600">{PENDING_TEXT[pendingOperation]}</p>
      )}

      {!loaded && (
        testing.casesStatus === 'loading'
          ? <p className="text-xs text-gray-600">Loading Agent Test Cases…</p>
          : (
            <button
              type="button"
              onClick={() => onLoadTestCases(agentKey)}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium"
            >
              Load Agent Test Cases
            </button>
          )
      )}

      {loaded && (
        <>
          <div className="space-y-2">
            {testing.cases.length > 0 ? (
              <div>
                <label htmlFor={`${id}-cases`} className="block text-xs font-medium text-gray-700">
                  Agent Test Cases
                </label>
                <select
                  id={`${id}-cases`}
                  value={selected?.id ?? ''}
                  onChange={(event) => {
                    setSelectedId(Number(event.currentTarget.value));
                    setConfirmingRetire(false);
                  }}
                  className="mt-1 block w-full rounded-md border border-gray-300 p-1 text-xs"
                >
                  {testing.cases.map((item) => (
                    <option key={item.id} value={item.id}>
                      {`${item.name} · v${item.version}${item.is_required ? ' · required' : ''}`}
                    </option>
                  ))}
                </select>
              </div>
            ) : <p className="text-xs text-gray-600">This role has no active Agent Test Cases.</p>}
            <button
              type="button"
              onClick={() => onLoadTestCases(agentKey)}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              Refresh test cases
            </button>
          </div>

          {selected !== null && (
            <div className="space-y-2">
              <p className="text-xs text-gray-600">
                {`Version ${selected.version} · ${selected.is_required ? 'Required' : 'Optional'} · `
                  + `Design system ${selected.assembly_context.design_system_active ? 'active' : 'inactive'}`}
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={operationsDisabled || candidateUnsaved}
                  onClick={() => { void onRunTestCase(agentKey, selected.id); }}
                  className="rounded-md bg-blue-600 px-2 py-1 text-xs font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
                >
                  Run test case
                </button>
                <button
                  type="button"
                  disabled={operationsDisabled}
                  onClick={() => { void onRunPublishedBaseline(agentKey, selected.id); }}
                  className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:text-gray-400"
                >
                  Run published baseline
                </button>
              </div>
              {candidateUnsaved && <p className="text-xs text-gray-600">{TEST_RUN_UNSAVED_HINT}</p>}
            </div>
          )}

          <div className="space-y-2">
            <p className="text-xs text-gray-600">{REPLACE_ORDER_HINT}</p>
            <div className="flex flex-wrap gap-2">
              {!adding && (
                <button
                  type="button"
                  disabled={operationsDisabled}
                  onClick={() => setAdding(true)}
                  className="rounded-md border border-gray-300 px-2 py-1 text-xs disabled:text-gray-400"
                >
                  Add test case
                </button>
              )}
              {selected !== null && !confirmingRetire && (
                <button
                  type="button"
                  disabled={operationsDisabled}
                  onClick={() => setConfirmingRetire(true)}
                  className="rounded-md border border-gray-300 px-2 py-1 text-xs disabled:text-gray-400"
                >
                  Retire test case
                </button>
              )}
            </div>
            {selected !== null && confirmingRetire && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
                <p>{`Retire ${selected.name} version ${selected.version}? A retired version cannot be run again.`}</p>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    disabled={operationsDisabled}
                    onClick={() => {
                      setConfirmingRetire(false);
                      void onRetireTestCase(agentKey, selected.id);
                    }}
                    className="rounded-md border border-amber-300 px-2 py-1 disabled:text-gray-400"
                  >
                    Confirm retire
                  </button>
                  <button type="button" onClick={() => setConfirmingRetire(false)} className="rounded-md px-2 py-1">
                    Keep test case
                  </button>
                </div>
              </div>
            )}
            {adding && (
              <AddTestCaseForm
                agentKey={agentKey}
                disabled={operationsDisabled}
                onCreate={(request) => onCreateTestCase(agentKey, request)}
                onClose={(created) => {
                  setAdding(false);
                  if (created !== null) setSelectedId(created.id);
                }}
              />
            )}
          </div>

          <div>
            <div role="tablist" aria-label="Test run views" className="flex gap-1 border-b border-gray-200">
              {VIEWS.map((name) => (
                <button
                  key={name}
                  type="button"
                  role="tab"
                  id={`${id}-tab-${name}`}
                  aria-selected={view === name}
                  aria-controls={`${id}-panel-${name}`}
                  tabIndex={view === name ? 0 : -1}
                  onClick={() => setView(name)}
                  onKeyDown={onTabKeyDown}
                  className={`px-2 py-1 text-xs ${view === name ? 'border-b-2 border-blue-600 font-medium text-blue-800' : 'text-gray-600'}`}
                >
                  {name}
                </button>
              ))}
            </div>
            <div
              role="tabpanel"
              id={`${id}-panel-${view}`}
              aria-labelledby={`${id}-tab-${view}`}
              className="space-y-3 pt-3"
            >
              {view === 'Input' && (
                <>
                  {selected === null
                    ? <p className="text-gray-600">No test case selected.</p>
                    : (
                      <section aria-label="Synthetic payload">
                        <h4 className="text-xs font-semibold text-gray-700">Synthetic payload</h4>
                        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-2 text-xs">
                          {jsonText(selected.synthetic_payload)}
                        </pre>
                      </section>
                    )}
                  <section aria-label="Assembled prompt">
                    <h4 className="text-xs font-semibold text-gray-700">Assembled prompt</h4>
                    {candidateEvidence === null
                      ? <p className="text-gray-600">{NO_RUN_YET}</p>
                      : (
                        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-2 text-xs">
                          {candidateEvidence.assembled_prompt ?? `No prompt was assembled (${candidateEvidence.execution_status}).`}
                        </pre>
                      )}
                  </section>
                  {candidateEvidence !== null && (
                    <section aria-label="Model payload sent">
                      <h4 className="text-xs font-semibold text-gray-700">Model payload sent</h4>
                      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-2 text-xs">
                        {jsonText(candidateEvidence.model_payload)}
                      </pre>
                    </section>
                  )}
                </>
              )}
              {view === 'Compare' && (
                <>
                  <section aria-label="Test case evidence">
                    <CandidateEvidence evidence={candidateEvidence} savedCandidateHash={savedCandidateHash} />
                  </section>
                  {baselineEvidence !== null && (
                    <section aria-label="Published baseline evidence" className="space-y-2 border-t border-gray-200 pt-3">
                      <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                        Published baseline rerun (not approved)
                      </h5>
                      <RunFacts evidence={baselineEvidence} />
                      {baselineEvidence.candidate_raw_output === null && baselineEvidence.candidate_structured_output === null
                        ? <p className="text-gray-600">No published output recorded.</p>
                        : (
                          <>
                            <EvidenceBlock label="Structured output" value={baselineEvidence.candidate_structured_output} />
                            <EvidenceBlock label="Raw output" value={baselineEvidence.candidate_raw_output} />
                          </>
                        )}
                    </section>
                  )}
                </>
              )}
              {view === 'Checks' && <ChecksView evidence={candidateEvidence} />}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
