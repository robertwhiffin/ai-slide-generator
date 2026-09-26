import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  syntheticAgentTestCase,
  syntheticAgentTestCaseList,
  syntheticInvalidTestCase,
  syntheticNullCandidateConflict,
  syntheticStaleTestCase,
  syntheticTestRunEvidence,
  syntheticTestRunUnavailable,
} from '../../../../tests/fixtures/mocks';
import {
  AgentDefinitionApiError,
  AgentTestApiError,
  InvalidTestRunResponseError,
  createTestCase,
  executeCandidateTestRun,
  executePublishedBaselineTestRun,
  getTestRun,
  listTestCaseRuns,
  listTestCases,
  retireTestCase,
  updateTestCase,
  type TestRunEvidence,
} from '../../../api/agentDefinitions';
import { emptyAgentTestingState, type AgentTestingState } from './draftEditorState';
import { TestRunPanel, type TestRunPanelProps } from './TestRunPanel';

const SYNTHETIC_DATA_WARNING =
  'Synthetic data only: never enter real customer, personal or confidential data.';
const REPLACE_ORDER_HINT =
  'To replace a test case, add the new case first and then retire the old one: '
  + 'a role cannot lose its last required case.';
const UNSAVED_HINT = "Save this role's edits before running a test case.";
const EDIT_HINT =
  'Edit test case saves a new version of the same case and keeps the old version as history.';

function readyTesting(overrides: Partial<AgentTestingState> = {}): AgentTestingState {
  return {
    ...emptyAgentTestingState(),
    casesStatus: 'ready',
    cases: [syntheticAgentTestCase()],
    ...overrides,
  };
}

function renderPanel(overrides: Partial<TestRunPanelProps> = {}) {
  const props: TestRunPanelProps = {
    agentKey: 'architect',
    testing: readyTesting(),
    savedCandidateHash: 'a'.repeat(64),
    candidateUnsaved: false,
    operationsDisabled: false,
    pendingOperation: null,
    onLoadTestCases: vi.fn(),
    onRunTestCase: vi.fn(),
    onRunPublishedBaseline: vi.fn(),
    onCreateTestCase: vi.fn().mockResolvedValue(null),
    onRetireTestCase: vi.fn(),
    onUpdateTestCase: vi.fn().mockResolvedValue(null),
    onLoadTestRuns: vi.fn(),
    onRecordVerdict: vi.fn().mockResolvedValue(true),
    ...overrides,
  };
  return { props, ...render(<TestRunPanel {...props} />) };
}

function openTab(name: 'Input' | 'Compare' | 'Checks') {
  fireEvent.click(screen.getByRole('tab', { name }));
  return screen.getByRole('tabpanel', { name });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('TestRunPanel', () => {
  it('says "No run yet" in every view when there is no evidence', () => {
    renderPanel({ testing: readyTesting({ candidateEvidence: null }) });

    expect(openTab('Input')).toHaveTextContent('No run yet');
    expect(openTab('Compare')).toHaveTextContent('No run yet');
    expect(openTab('Checks')).toHaveTextContent('No run yet');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('says "Baseline not recorded" when the run stored no baseline, and still shows the candidate', () => {
    renderPanel({
      testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence({ baseline_raw_output: null }) }),
    });

    const compare = openTab('Compare');
    const evidence = within(compare).getByRole('region', { name: 'Test case evidence' });
    expect(evidence).toHaveTextContent('Baseline not recorded');
    expect(evidence).toHaveTextContent('Synthetic candidate structured title');
    expect(evidence).toHaveTextContent('Synthetic candidate raw title');
  });

  it('shows a stored baseline beside the candidate, labelled not approved (P1)', () => {
    renderPanel({
      testing: readyTesting({
        candidateEvidence: syntheticTestRunEvidence({
          baseline_raw_output: { title: 'Stored baseline raw title' },
          baseline_structured_output: { title: 'Stored baseline structured title' },
        }),
      }),
    });

    const evidence = within(openTab('Compare')).getByRole('region', { name: 'Test case evidence' });
    expect(evidence).not.toHaveTextContent('Baseline not recorded');
    expect(evidence).toHaveTextContent('Stored baseline structured title');
    expect(evidence).toHaveTextContent('Stored baseline raw title');
    expect(evidence).toHaveTextContent('Published baseline (not approved)');
  });

  it('renders a failed deterministic check by name in a failed state, with its message and issues', () => {
    renderPanel({
      testing: readyTesting({
        candidateEvidence: syntheticTestRunEvidence({
          execution_status: 'incomplete',
          deterministic_checks_passed: false,
          deterministic_check_results: [
            { name: 'execution', passed: true, message: null, issues: [] },
            {
              name: 'output_contract',
              passed: false,
              message: 'The structured output omitted a required field.',
              issues: [{ code: 'missing', field: 'title' }],
            },
          ],
        }),
      }),
    });

    const checks = openTab('Checks');
    expect(checks).toHaveTextContent('Deterministic checks failed');
    const rows = within(checks).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    const failed = rows.find((row) => within(row).queryByText('output_contract'));
    expect(failed).toHaveAttribute('data-check-state', 'failed');
    expect(within(failed!).getByText('Failed')).toBeInTheDocument();
    expect(failed).toHaveTextContent('The structured output omitted a required field.');
    expect(failed).toHaveTextContent('missing (title)');
    const passed = rows.find((row) => within(row).queryByText('execution'));
    expect(passed).toHaveAttribute('data-check-state', 'passed');
    expect(within(passed!).getByText('Passed')).toBeInTheDocument();
  });

  it.each([
    ['not loaded', emptyAgentTestingState()],
    ['loaded with no cases', readyTesting({ cases: [] })],
    ['loaded with a case', readyTesting()],
  ])('shows the synthetic-data warning unconditionally when %s', (_label, testing) => {
    renderPanel({ testing });

    expect(screen.getByText(SYNTHETIC_DATA_WARNING)).toBeInTheDocument();
  });

  it('puts the synthetic-data warning beside the payload editor and describes the editor with it', () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Add test case' }));
    const editor = screen.getByRole('textbox', { name: 'Synthetic payload (JSON)' });
    const describedBy = editor.getAttribute('aria-describedby')?.split(' ') ?? [];
    const warnings = describedBy.map((id) => document.getElementById(id)?.textContent);
    expect(warnings).toContain(SYNTHETIC_DATA_WARNING);
    expect(editor.parentElement).toHaveTextContent(SYNTHETIC_DATA_WARNING);
  });

  it('renders model output, prompt and payload verbatim as text, never as markup', () => {
    const markup = '<img src="x" onerror="window.__tellrXss = 1"><b>bold</b>';
    const { container } = renderPanel({
      testing: readyTesting({
        cases: [syntheticAgentTestCase({ synthetic_payload: { user_request: markup } })],
        candidateEvidence: syntheticTestRunEvidence({
          assembled_prompt: markup,
          candidate_raw_output: { title: markup },
          candidate_structured_output: { title: markup },
          baseline_raw_output: { title: markup },
          baseline_structured_output: { title: markup },
          deterministic_checks_passed: false,
          deterministic_check_results: [{ name: 'output_contract', passed: false, message: markup, issues: [] }],
        }),
      }),
    });

    for (const tab of ['Input', 'Compare', 'Checks'] as const) {
      openTab(tab);
      expect(container.querySelector('img')).toBeNull();
      expect(container.querySelector('b')).toBeNull();
    }
    expect(openTab('Input')).toHaveTextContent('<img src="x"');
    expect(openTab('Compare')).toHaveTextContent('<b>bold</b>');
  });

  it('shows the assembled prompt and the projected model payload of the selected case run', () => {
    renderPanel({ testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }) });

    const input = openTab('Input');
    expect(input).toHaveTextContent('Synthetic assembled Architect prompt for the saved candidate.');
    const sent = within(input).getByRole('region', { name: 'Model payload sent' });
    expect(sent).toHaveTextContent('Outline a five-slide quarterly revenue review');
    expect(sent).not.toHaveTextContent('synthetic-session-0001');
    expect(within(input).getByRole('region', { name: 'Synthetic payload' }))
      .toHaveTextContent('synthetic-session-0001');
  });

  it('displays missing token usage as "not reported" and reported usage as numbers (P9)', () => {
    const { rerender, props } = renderPanel({
      testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }),
    });
    const evidence = () => within(openTab('Compare')).getByRole('region', { name: 'Test case evidence' });
    expect(evidence()).toHaveTextContent('Input tokens: not reported');
    expect(evidence()).toHaveTextContent('Output tokens: not reported');
    expect(evidence()).toHaveTextContent('Latency: 812.5 ms');

    rerender(<TestRunPanel
      {...props}
      testing={readyTesting({
        candidateEvidence: syntheticTestRunEvidence({ input_tokens: 1200, output_tokens: 340, latency_ms: null }),
      })}
    />);
    expect(evidence()).toHaveTextContent('Input tokens: 1200');
    expect(evidence()).toHaveTextContent('Output tokens: 340');
    expect(evidence()).toHaveTextContent('Latency: not reported');
  });

  it('shows a model_error run as saved evidence with its code and no outputs', () => {
    renderPanel({
      testing: readyTesting({
        candidateEvidence: syntheticTestRunEvidence({
          execution_status: 'model_error',
          error_detail: 'provider_unavailable',
          candidate_raw_output: null,
          candidate_structured_output: null,
          deterministic_checks_passed: false,
          deterministic_check_results: [
            { name: 'execution', passed: false, message: null, issues: [{ code: 'provider_unavailable', field: null }] },
          ],
        }),
      }),
    });

    const evidence = within(openTab('Compare')).getByRole('region', { name: 'Test case evidence' });
    expect(evidence).toHaveTextContent('Status: model_error');
    expect(evidence).toHaveTextContent('Error: provider_unavailable');
    expect(evidence).toHaveTextContent('No candidate output recorded');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('never shows another case\'s evidence as the selected case\'s', () => {
    renderPanel({
      testing: readyTesting({
        cases: [syntheticAgentTestCase(), syntheticAgentTestCase({ id: 102, name: 'Architect second case' })],
        candidateEvidence: syntheticTestRunEvidence({ test_case_id: 102 }),
      }),
    });

    expect(openTab('Compare')).toHaveTextContent('No run yet');
    fireEvent.change(screen.getByRole('combobox', { name: 'Agent Test Cases' }), { target: { value: '102' } });
    expect(openTab('Compare')).toHaveTextContent('Synthetic candidate structured title');
  });

  it('marks evidence for an earlier saved candidate', () => {
    renderPanel({
      savedCandidateHash: 'd'.repeat(64),
      testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }),
    });

    expect(within(openTab('Compare')).getByRole('region', { name: 'Test case evidence' }))
      .toHaveTextContent('This run tested an earlier saved candidate.');
  });

  it('shows the published baseline rerun as soon as it exists, labelled not approved (P1)', () => {
    renderPanel({
      testing: readyTesting({
        baselineEvidence: syntheticTestRunEvidence({
          run_id: 777,
          run_kind: 'published_baseline',
          candidate_structured_output: { title: 'Published rerun title' },
        }),
      }),
    });

    const region = within(openTab('Compare')).getByRole('region', { name: 'Published baseline evidence' });
    expect(region).toHaveTextContent('Published rerun title');
    expect(region).toHaveTextContent('not approved');
  });

  it('refuses a candidate run while the role has unsaved edits and explains why', () => {
    const { props } = renderPanel({ candidateUnsaved: true });

    const run = screen.getByRole('button', { name: 'Run test case' });
    expect(run).toBeDisabled();
    expect(screen.getByText(UNSAVED_HINT)).toBeInTheDocument();
    fireEvent.click(run);
    expect(props.onRunTestCase).not.toHaveBeenCalled();
    // The published baseline does not read the draft, so unsaved edits do not block it.
    expect(screen.getByRole('button', { name: 'Run published baseline' })).toBeEnabled();
  });

  it('disables every test operation while the one gate is held', () => {
    renderPanel({ operationsDisabled: true });

    for (const name of ['Run test case', 'Run published baseline', 'Add test case', 'Retire test case', 'Edit test case']) {
      expect(screen.getByRole('button', { name })).toBeDisabled();
    }
  });

  it('runs the selected active case by id and names the pending run', () => {
    const { props, rerender } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Run test case' }));
    expect(props.onRunTestCase).toHaveBeenCalledWith('architect', 101);
    fireEvent.click(screen.getByRole('button', { name: 'Run published baseline' }));
    expect(props.onRunPublishedBaseline).toHaveBeenCalledWith('architect', 101);

    rerender(<TestRunPanel {...props} operationsDisabled pendingOperation="testRun" />);
    expect(screen.getByText('Running the test case against the saved candidate…')).toBeInTheDocument();
  });

  it('offers only the load control before the role\'s cases are read', () => {
    const { props } = renderPanel({ testing: emptyAgentTestingState() });

    expect(screen.queryByRole('button', { name: 'Run test case' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load Agent Test Cases' }));
    expect(props.onLoadTestCases).toHaveBeenCalledWith('architect');
  });

  it('states the add-then-retire order next to the retire control (P3)', () => {
    renderPanel();

    expect(screen.getByText(REPLACE_ORDER_HINT)).toBeInTheDocument();
  });

  it('asks for confirmation before retiring and retires exactly the selected version', () => {
    const { props } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Retire test case' }));
    expect(props.onRetireTestCase).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep test case' }));
    expect(screen.queryByRole('button', { name: 'Confirm retire' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retire test case' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm retire' }));
    expect(props.onRetireTestCase).toHaveBeenCalledWith('architect', 101);
  });

  it('refuses a payload that is not a JSON object locally and sends exactly the typed case otherwise', async () => {
    const onCreateTestCase = vi.fn().mockResolvedValue(syntheticAgentTestCase({ id: 202, name: 'New case' }));
    renderPanel({ onCreateTestCase });

    fireEvent.click(screen.getByRole('button', { name: 'Add test case' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Test case name' }), { target: { value: 'New case' } });
    const payload = screen.getByRole('textbox', { name: 'Synthetic payload (JSON)' });
    for (const invalid of ['{', '[]', '"text"', 'null']) {
      fireEvent.change(payload, { target: { value: invalid } });
      fireEvent.click(screen.getByRole('button', { name: 'Save test case' }));
      expect(screen.getByText('The synthetic payload must be a JSON object.')).toBeInTheDocument();
    }
    expect(onCreateTestCase).not.toHaveBeenCalled();

    fireEvent.change(payload, { target: { value: '{"user_request": "Synthetic ask"}' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Design system active' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save test case' }));
    await vi.waitFor(() => expect(onCreateTestCase).toHaveBeenCalledTimes(1));
    expect(onCreateTestCase).toHaveBeenCalledWith('architect', {
      agent_key: 'architect',
      name: 'New case',
      synthetic_payload: { user_request: 'Synthetic ask' },
      assembly_context: { design_system_active: true },
      is_required: false,
    });
  });

  it('distinguishes editing a case (a new version) from replacing it with another (add, then retire)', () => {
    renderPanel();

    expect(screen.getByText(EDIT_HINT)).toBeInTheDocument();
    expect(screen.getByText(REPLACE_ORDER_HINT)).toBeInTheDocument();
  });

  it('edits the selected case as a new version with its name fixed, sending exactly the supersede body', async () => {
    const onUpdateTestCase = vi.fn().mockResolvedValue(syntheticAgentTestCase({ id: 111, version: 2 }));
    renderPanel({ onUpdateTestCase });

    fireEvent.click(screen.getByRole('button', { name: 'Edit test case' }));
    expect(screen.queryByRole('textbox', { name: 'Test case name' })).not.toBeInTheDocument();
    expect(screen.getByText('Name: Architect quarterly revenue outline')).toBeInTheDocument();
    const payload = screen.getByRole('textbox', { name: 'Synthetic payload (JSON)' });
    expect(JSON.parse((payload as HTMLTextAreaElement).value)).toEqual(syntheticAgentTestCase().synthetic_payload);
    expect(screen.getByRole('checkbox', { name: 'Required test case' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Design system active' })).not.toBeChecked();
    expect(payload.parentElement).toHaveTextContent(SYNTHETIC_DATA_WARNING);

    fireEvent.change(payload, { target: { value: '[]' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save new version' }));
    expect(screen.getByText('The synthetic payload must be a JSON object.')).toBeInTheDocument();
    expect(onUpdateTestCase).not.toHaveBeenCalled();

    fireEvent.change(payload, { target: { value: '{"user_request": "Revised synthetic ask"}' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Design system active' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save new version' }));
    await vi.waitFor(() => expect(onUpdateTestCase).toHaveBeenCalledTimes(1));
    expect(onUpdateTestCase).toHaveBeenCalledWith('architect', 101, {
      name: 'Architect quarterly revenue outline',
      synthetic_payload: { user_request: 'Revised synthetic ask' },
      assembly_context: { design_system_active: true },
      is_required: true,
    });
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Save new version' })).not.toBeInTheDocument());
  });

  it('keeps the edit form open when the new version is refused', async () => {
    renderPanel({ onUpdateTestCase: vi.fn().mockResolvedValue(null) });

    fireEvent.click(screen.getByRole('button', { name: 'Edit test case' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save new version' }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole('button', { name: 'Save new version' })).toBeInTheDocument();
  });

  it('reads the selected case version\'s history once, again on a case switch, and not for a case already read', () => {
    const cases = [syntheticAgentTestCase(), syntheticAgentTestCase({ id: 102, name: 'Architect second case' })];
    const { props } = renderPanel({ testing: readyTesting({ cases }) });
    expect(props.onLoadTestRuns).toHaveBeenCalledTimes(1);
    expect(props.onLoadTestRuns).toHaveBeenCalledWith('architect', 101);

    fireEvent.change(screen.getByRole('combobox', { name: 'Agent Test Cases' }), { target: { value: '102' } });
    expect(props.onLoadTestRuns).toHaveBeenLastCalledWith('architect', 102);

    const onLoadTestRuns = vi.fn();
    renderPanel({ onLoadTestRuns, testing: readyTesting({ cases, historyCaseId: 101 }) });
    expect(onLoadTestRuns).not.toHaveBeenCalled();
    // No read before the case list is loaded.
    const idle = vi.fn();
    renderPanel({ onLoadTestRuns: idle, testing: emptyAgentTestingState() });
    expect(idle).not.toHaveBeenCalled();
  });

  it('shows the panel notice without an alert', () => {
    renderPanel({ testing: readyTesting({ notice: 'No change: this content matches version 1, so no new version was created.' }) });

    expect(screen.getByText('No change: this content matches version 1, so no new version was created.'))
      .toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows a contained panel error and the ordered server issues', () => {
    renderPanel({
      testing: readyTesting({
        error: 'The test case was refused.',
        issues: [
          { field: 'is_active', code: 'last_required_case', message: 'The last required case cannot be retired.' },
          { field: 'name', code: 'duplicate_name', message: 'A case with this name already exists.' },
        ],
      }),
    });

    expect(screen.getByRole('alert')).toHaveTextContent('The test case was refused.');
    const items = within(screen.getByRole('list', { name: 'Test case issues' })).getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'is_active: The last required case cannot be retired.',
      'name: A case with this name already exists.',
    ]);
  });
});

// ============================================================
// #268 verdict controls (C26)
// ============================================================

const ONLY_COMPLETED = 'Only completed runs can be reviewed';
const CHECKS_DID_NOT_PASS = 'Deterministic checks did not pass';

function reviewed(overrides: Partial<TestRunEvidence> = {}): TestRunEvidence {
  return syntheticTestRunEvidence({
    candidate_is_current: null,
    base_release_is_current: null,
    verdict: 'approved',
    verdict_reviewer: 'reviewer@test.com',
    verdict_at: '2026-09-26T10:05:00Z',
    verdict_notes: 'Looks <b>right</b>.',
    ...overrides,
  });
}

function candidateVerdict() {
  return within(openTab('Compare')).getByRole('region', { name: 'Candidate run verdict' });
}

describe('TestRunPanel verdict controls', () => {
  it('offers Approve run and Reject run on a completed, passing, unreviewed candidate run', () => {
    renderPanel({ testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }) });

    const region = candidateVerdict();
    expect(region).toHaveTextContent('No verdict recorded');
    expect(within(region).getByRole('button', { name: 'Approve run' })).toBeEnabled();
    expect(within(region).getByRole('button', { name: 'Reject run' })).toBeEnabled();
    expect(region).not.toHaveTextContent(CHECKS_DID_NOT_PASS);
    expect(region).not.toHaveTextContent(ONLY_COMPLETED);
  });

  it('disables Approve run with visible reason text when the deterministic checks failed, and keeps Reject run', () => {
    renderPanel({
      testing: readyTesting({
        candidateEvidence: syntheticTestRunEvidence({
          deterministic_checks_passed: false,
          deterministic_check_results: [
            { name: 'execution', passed: true, message: null, issues: [] },
            { name: 'output_contract', passed: false, message: 'Missing title.', issues: [] },
          ],
        }),
      }),
    });

    const region = candidateVerdict();
    const approve = within(region).getByRole('button', { name: 'Approve run' });
    expect(approve).toBeDisabled();
    expect(within(region).getByText(CHECKS_DID_NOT_PASS)).toBeVisible();
    expect(approve).toHaveAccessibleDescription(CHECKS_DID_NOT_PASS);
    expect(within(region).getByRole('button', { name: 'Reject run' })).toBeEnabled();
  });

  it.each(['model_error', 'assembly_error', 'incomplete'] as const)(
    'disables both controls with visible reason text on a %s run',
    (status) => {
      renderPanel({
        testing: readyTesting({
          candidateEvidence: syntheticTestRunEvidence({ execution_status: status, deterministic_checks_passed: status === 'incomplete' }),
        }),
      });

      const region = candidateVerdict();
      expect(within(region).getByRole('button', { name: 'Approve run' })).toBeDisabled();
      expect(within(region).getByRole('button', { name: 'Reject run' })).toBeDisabled();
      expect(within(region).getByText(ONLY_COMPLETED)).toBeVisible();
    },
  );

  it('disables both controls while the one gate is held', () => {
    renderPanel({ testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }), operationsDisabled: true });

    const region = candidateVerdict();
    expect(within(region).getByRole('button', { name: 'Approve run' })).toBeDisabled();
    expect(within(region).getByRole('button', { name: 'Reject run' })).toBeDisabled();
  });

  it('sends the verdict with the optional notes, and null when the notes are blank', async () => {
    const evidence = syntheticTestRunEvidence();
    const onRecordVerdict = vi.fn().mockResolvedValue(true);
    renderPanel({ testing: readyTesting({ candidateEvidence: evidence }), onRecordVerdict });

    const region = candidateVerdict();
    const notes = within(region).getByRole('textbox', { name: 'Candidate run verdict notes' });
    expect(notes).toHaveAttribute('maxLength', '2000');
    fireEvent.change(notes, { target: { value: 'Tone is right.' } });
    await act(async () => { fireEvent.click(within(region).getByRole('button', { name: 'Approve run' })); });
    expect(onRecordVerdict).toHaveBeenLastCalledWith('architect', evidence, 'approved', 'Tone is right.');
    // The notes clear once the verdict settles.
    expect(notes).toHaveValue('');

    fireEvent.change(notes, { target: { value: '   ' } });
    await act(async () => { fireEvent.click(within(region).getByRole('button', { name: 'Reject run' })); });
    expect(onRecordVerdict).toHaveBeenLastCalledWith('architect', evidence, 'rejected', null);
  });

  it('keeps the typed notes when the verdict was refused, so the admin can retry without retyping', async () => {
    const onRecordVerdict = vi.fn().mockResolvedValue(false);
    renderPanel({ testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }), onRecordVerdict });

    const region = candidateVerdict();
    const notes = within(region).getByRole('textbox', { name: 'Candidate run verdict notes' });
    fireEvent.change(notes, { target: { value: 'Tone is right.' } });
    await act(async () => { fireEvent.click(within(region).getByRole('button', { name: 'Approve run' })); });

    expect(onRecordVerdict).toHaveBeenCalledTimes(1);
    expect(notes).toHaveValue('Tone is right.');
  });

  it('an approved run shows its reviewer, time and notes as text only, and offers only Reject run', () => {
    const { container } = renderPanel({ testing: readyTesting({ candidateEvidence: reviewed() }) });

    const region = candidateVerdict();
    expect(region).toHaveTextContent('Approved by reviewer@test.com at 2026-09-26T10:05:00Z');
    expect(region).toHaveTextContent('Notes: Looks <b>right</b>.');
    expect(container.querySelector('b')).toBeNull();
    expect(within(region).queryByRole('button', { name: 'Approve run' })).not.toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Reject run' })).toBeEnabled();
  });

  it('a rejected run offers Approve run when it is eligible, and not Reject run', () => {
    renderPanel({ testing: readyTesting({ candidateEvidence: reviewed({ verdict: 'rejected', verdict_notes: null }) }) });

    const region = candidateVerdict();
    expect(region).toHaveTextContent('Rejected by reviewer@test.com at 2026-09-26T10:05:00Z');
    expect(region).not.toHaveTextContent('Notes:');
    expect(within(region).getByRole('button', { name: 'Approve run' })).toBeEnabled();
    expect(within(region).queryByRole('button', { name: 'Reject run' })).not.toBeInTheDocument();
  });

  it('a rejected run whose checks failed keeps Approve run disabled with its reason', () => {
    renderPanel({
      testing: readyTesting({
        candidateEvidence: reviewed({ verdict: 'rejected', verdict_notes: null, deterministic_checks_passed: false }),
      }),
    });

    const region = candidateVerdict();
    expect(within(region).getByRole('button', { name: 'Approve run' })).toBeDisabled();
    expect(within(region).getByText(CHECKS_DID_NOT_PASS)).toBeVisible();
  });

  it.each([null, 'approved', 'rejected'] as const)(
    'labels the baseline column inside a %s candidate run "(not approved)": the candidate\'s verdict is not the baseline\'s',
    (verdict) => {
      const evidence = verdict === null
        ? syntheticTestRunEvidence({ baseline_structured_output: { title: 'Stored baseline' } })
        : reviewed({ verdict, baseline_structured_output: { title: 'Stored baseline' } });
      renderPanel({ testing: readyTesting({ candidateEvidence: evidence }) });

      const region = within(openTab('Compare')).getByRole('region', { name: 'Test case evidence' });
      expect(region).toHaveTextContent('Published baseline (not approved)');
      expect(region).not.toHaveTextContent('Published baseline (approved)');
      expect(region).not.toHaveTextContent('Published baseline (rejected)');
    },
  );

  it('an approved candidate keeps its baseline column "(not approved)" while an approved baseline rerun reads "(approved)"', () => {
    renderPanel({
      testing: readyTesting({
        candidateEvidence: reviewed({ baseline_structured_output: { title: 'Stored baseline' } }),
        baselineEvidence: reviewed({ run_id: 777, run_kind: 'published_baseline' }),
      }),
    });

    const compare = openTab('Compare');
    expect(within(compare).getByRole('region', { name: 'Test case evidence' }))
      .toHaveTextContent('Published baseline (not approved)');
    expect(within(compare).getByRole('region', { name: 'Published baseline evidence' }))
      .toHaveTextContent('Published baseline rerun (approved)');
  });

  it('offers the controls on the published baseline rerun too (P1), with a verdict-aware label', async () => {
    const baseline = syntheticTestRunEvidence({ run_id: 777, run_kind: 'published_baseline' });
    const onRecordVerdict = vi.fn().mockResolvedValue(true);
    const { rerender, props } = renderPanel({ testing: readyTesting({ baselineEvidence: baseline }), onRecordVerdict });

    const compare = openTab('Compare');
    const section = within(compare).getByRole('region', { name: 'Published baseline evidence' });
    expect(section).toHaveTextContent('Published baseline rerun (not approved)');
    const region = within(section).getByRole('region', { name: 'Published baseline verdict' });
    await act(async () => { fireEvent.click(within(region).getByRole('button', { name: 'Approve run' })); });
    expect(onRecordVerdict).toHaveBeenCalledWith('architect', baseline, 'approved', null);

    rerender(<TestRunPanel {...props} testing={readyTesting({ baselineEvidence: reviewed({ run_id: 777, run_kind: 'published_baseline' }) })} />);
    expect(within(screen.getByRole('tabpanel', { name: 'Compare' })).getByRole('region', { name: 'Published baseline evidence' }))
      .toHaveTextContent('Published baseline rerun (approved)');
  });

  it('says a verdict is being recorded while the verdict holds the gate', () => {
    renderPanel({ testing: readyTesting({ candidateEvidence: syntheticTestRunEvidence() }), pendingOperation: 'verdict' });

    expect(screen.getByText('Recording the verdict…')).toBeInTheDocument();
  });
});

// ============================================================
// The typed #267 clients
// ============================================================

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: vi.fn().mockResolvedValue(body),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function onlyCall(fetchMock: ReturnType<typeof vi.fn>) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  return fetchMock.mock.calls[0] as [string, RequestInit];
}

/** A stored run carrying a recorded verdict (#268 C16): read back, so the flags are null. */
function approvedEvidence(overrides: Partial<TestRunEvidence> = {}): TestRunEvidence {
  return syntheticTestRunEvidence({
    candidate_is_current: null,
    base_release_is_current: null,
    verdict: 'approved',
    verdict_reviewer: 'reviewer@test.com',
    verdict_at: '2026-09-26T10:05:00Z',
    verdict_notes: 'Looks right.',
    ...overrides,
  });
}

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('expected a rejection');
}

describe('the test run client', () => {
  it('runs the saved candidate with exactly the case and the lock', async () => {
    const fetchMock = stubFetch(201, syntheticTestRunEvidence());

    const evidence = await executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 3 });

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/draft\/architect\/test-runs$/);
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"test_case_id":101,"lock_version":3}');
    expect(evidence).toEqual(syntheticTestRunEvidence());
  });

  it('reruns the published baseline with exactly the case and no lock', async () => {
    const baseline = syntheticTestRunEvidence({ run_kind: 'published_baseline' });
    const fetchMock = stubFetch(201, baseline);

    const evidence = await executePublishedBaselineTestRun('architect', { test_case_id: 101 });

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/published\/architect\/test-runs$/);
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"test_case_id":101}');
    expect(evidence).toEqual(baseline);
  });

  it('accepts a 201 model_error run as saved evidence, not as an error', async () => {
    const failed = syntheticTestRunEvidence({
      execution_status: 'model_error',
      error_detail: 'provider_unavailable',
      candidate_raw_output: null,
      candidate_structured_output: null,
      deterministic_checks_passed: false,
    });
    stubFetch(201, failed);

    await expect(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }))
      .resolves.toEqual(failed);
  });

  it.each([
    ['an approval with notes', approvedEvidence()],
    ['an approval without notes', approvedEvidence({ verdict_notes: null })],
    ['a rejection', approvedEvidence({ verdict: 'rejected', verdict_notes: 'Wrong tone.' })],
  ])('accepts stored evidence carrying %s', async (_label, body) => {
    stubFetch(200, body);

    await expect(getTestRun(501)).resolves.toEqual(body);
  });

  it.each([
    ['an unknown key', { ...syntheticTestRunEvidence(), verdict_by: 'admin@test.com' }],
    ['a missing verdict key', (() => {
      const rest: Record<string, unknown> = { ...syntheticTestRunEvidence() };
      delete rest.verdict_notes;
      return rest;
    })()],
    ['an unknown verdict', { ...syntheticTestRunEvidence(), verdict: 'passed' }],
    ['a verdict with no reviewer', { ...approvedEvidence(), verdict_reviewer: null }],
    ['a verdict with no time', { ...approvedEvidence(), verdict_at: null }],
    ['a reviewer with no verdict', syntheticTestRunEvidence({ verdict_reviewer: 'admin@test.com' })],
    ['a time with no verdict', syntheticTestRunEvidence({ verdict_at: '2026-09-26T10:05:00Z' })],
    ['notes with no verdict', syntheticTestRunEvidence({ verdict_notes: 'Orphan note.' })],
    ['a non-string reviewer', { ...approvedEvidence(), verdict_reviewer: 7 }],
    ['a non-string notes value', { ...approvedEvidence(), verdict_notes: 7 }],
    ['a missing field', (() => {
      const rest: Record<string, unknown> = { ...syntheticTestRunEvidence() };
      delete rest.run_by;
      return rest;
    })()],
    ['a -1 sentinel release', syntheticTestRunEvidence({ compared_release_id: -1 })],
    ['a -1 sentinel revision', syntheticTestRunEvidence({ compared_definition_revision_id: -1 })],
    ['an unknown run kind', { ...syntheticTestRunEvidence(), run_kind: 'approved_baseline' }],
    ['an unknown status', { ...syntheticTestRunEvidence(), execution_status: 'passed' }],
    ['an uppercase hash', syntheticTestRunEvidence({ candidate_hash: 'A'.repeat(64) })],
    ['an unknown role', { ...syntheticTestRunEvidence(), agent_key: 'foreman' }],
    ['a non-object output', { ...syntheticTestRunEvidence(), candidate_raw_output: '<b>text</b>' }],
    ['a check with an extra key', {
      ...syntheticTestRunEvidence(),
      deterministic_check_results: [{ name: 'execution', passed: true, message: null, issues: [], html: '' }],
    }],
    ['an unknown check name', {
      ...syntheticTestRunEvidence(),
      deterministic_check_results: [{ name: 'judge', passed: true, message: null, issues: [] }],
    }],
    ['a string token count', { ...syntheticTestRunEvidence(), input_tokens: '12' }],
    ['a non-boolean currency flag', { ...syntheticTestRunEvidence(), candidate_is_current: 'yes' }],
  ])('contains a 201 body with %s as InvalidTestRunResponseError', async (_label, body) => {
    stubFetch(201, body);

    expect(await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 })))
      .toBeInstanceOf(InvalidTestRunResponseError);
  });

  it('surfaces a stale_draft 409 as the probe-style null-candidate conflict', async () => {
    const conflict = syntheticNullCandidateConflict(0, 1);
    stubFetch(409, conflict);

    const error = await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }));

    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect((error as AgentDefinitionApiError).status).toBe(409);
    expect((error as AgentDefinitionApiError).payload).toEqual(conflict);
  });

  it('surfaces a stale_test_case 409 as a typed failure', async () => {
    stubFetch(409, syntheticStaleTestCase(101));

    const error = await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }));

    expect(error).toBeInstanceOf(AgentTestApiError);
    expect((error as AgentTestApiError).status).toBe(409);
    expect((error as AgentTestApiError).failure).toEqual(syntheticStaleTestCase(101));
  });

  it('surfaces an invalid_draft 422 as the draft rejection and an invalid_test_case 422 as a typed failure', async () => {
    const draftRejection = {
      code: 'invalid_draft',
      errors: [{
        field: 'candidate.model.endpoint_name',
        code: 'endpoint_url_not_allowed',
        message: 'Endpoint must be a Databricks endpoint name, not a URL.',
      }],
    };
    stubFetch(422, draftRejection);
    const draftError = await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }));
    expect(draftError).toBeInstanceOf(AgentDefinitionApiError);
    expect((draftError as AgentDefinitionApiError).payload).toEqual(draftRejection);

    const mismatch = syntheticInvalidTestCase([{
      field: 'test_case_id', code: 'agent_key_mismatch', message: 'The test case belongs to another role.',
    }]);
    stubFetch(422, mismatch);
    const caseError = await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }));
    expect(caseError).toBeInstanceOf(AgentTestApiError);
    expect((caseError as AgentTestApiError).failure).toEqual(mismatch);
  });

  it('surfaces the exact 404 as a typed missing case and any other 404 as a plain API error', async () => {
    stubFetch(404, { detail: 'Test case not found' });
    const missing = await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }));
    expect(missing).toBeInstanceOf(AgentTestApiError);
    expect((missing as AgentTestApiError).failure).toEqual({ code: 'test_case_not_found' });

    stubFetch(404, { detail: 'Not Found' });
    const other = await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 }));
    expect(other).toBeInstanceOf(AgentDefinitionApiError);
    expect(other).not.toBeInstanceOf(AgentTestApiError);
  });

  it('surfaces the exact 503 as a retryable typed failure and a proxy 503 as a plain API error', async () => {
    stubFetch(503, syntheticTestRunUnavailable());
    const unavailable = await rejection(executePublishedBaselineTestRun('architect', { test_case_id: 101 }));
    expect(unavailable).toBeInstanceOf(AgentTestApiError);
    expect((unavailable as AgentTestApiError).failure).toEqual(syntheticTestRunUnavailable());

    stubFetch(503, { detail: 'upstream connect error' });
    const proxy = await rejection(executePublishedBaselineTestRun('architect', { test_case_id: 101 }));
    expect(proxy).toBeInstanceOf(AgentDefinitionApiError);
    expect(proxy).not.toBeInstanceOf(AgentTestApiError);
  });

  it.each([
    [409, { code: 'stale_draft' }],
    [422, { code: 'invalid_test_case', issues: [] }],
    [422, { code: 'invalid_draft', errors: 'x' }],
  ])('contains a malformed %i body as InvalidTestRunResponseError', async (status, body) => {
    stubFetch(status, body);

    expect(await rejection(executeCandidateTestRun('architect', { test_case_id: 101, lock_version: 0 })))
      .toBeInstanceOf(InvalidTestRunResponseError);
  });

  it('reads one run and a case version\'s run history, where currency flags are null', async () => {
    const stored = syntheticTestRunEvidence({ candidate_is_current: null, base_release_is_current: null });
    const runFetch = stubFetch(200, stored);
    await expect(getTestRun(501)).resolves.toEqual(stored);
    const [runUrl, runInit] = onlyCall(runFetch);
    expect(runUrl).toMatch(/\/api\/admin\/agent-definitions\/test-runs\/501$/);
    expect(runInit.method).toBe('GET');

    const listFetch = stubFetch(200, { items: [stored] });
    await expect(listTestCaseRuns(101)).resolves.toEqual([stored]);
    const [listUrl] = onlyCall(listFetch);
    expect(listUrl).toMatch(/\/api\/admin\/agent-definitions\/test-cases\/101\/runs$/);

    const limitedFetch = stubFetch(200, { items: [stored] });
    await expect(listTestCaseRuns(101, 100)).resolves.toEqual([stored]);
    expect(onlyCall(limitedFetch)[0]).toMatch(/\/test-cases\/101\/runs\?limit=100$/);
  });
});

describe('the test case supersede client', () => {
  const request = {
    name: 'Architect quarterly revenue outline',
    synthetic_payload: { user_request: 'Revised synthetic ask' },
    assembly_context: { design_system_active: true },
    is_required: true,
  };

  it('supersedes one version with exactly the update body', async () => {
    const next = syntheticAgentTestCase({ id: 111, version: 2 });
    const fetchMock = stubFetch(200, next);

    await expect(updateTestCase(101, request)).resolves.toEqual(next);

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/test-cases\/101$/);
    expect(init.method).toBe('PUT');
    expect(Object.keys(JSON.parse(String(init.body)))).toEqual([
      'name', 'synthetic_payload', 'assembly_context', 'is_required',
    ]);
    expect(JSON.parse(String(init.body))).toEqual(request);
  });

  it('surfaces a stale 409, an ordered 422 and an inactive 200 exactly', async () => {
    stubFetch(409, syntheticStaleTestCase(101));
    expect(((await rejection(updateTestCase(101, request))) as AgentTestApiError).failure)
      .toEqual(syntheticStaleTestCase(101));

    const refused = syntheticInvalidTestCase([{ field: 'is_required', code: 'last_required_case', message: 'x' }]);
    stubFetch(422, refused);
    expect(((await rejection(updateTestCase(101, request))) as AgentTestApiError).failure).toEqual(refused);

    stubFetch(200, syntheticAgentTestCase({ is_active: false }));
    expect(await rejection(updateTestCase(101, request))).toBeInstanceOf(InvalidTestRunResponseError);
  });
});

describe('the test case client', () => {
  it('lists one role\'s active cases', async () => {
    const fetchMock = stubFetch(200, syntheticAgentTestCaseList());

    await expect(listTestCases('architect')).resolves.toEqual([syntheticAgentTestCase()]);

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/test-cases\?agent_key=architect$/);
    expect(init.method).toBe('GET');
  });

  it.each([
    ['an extra key', { items: [{ ...syntheticAgentTestCase(), secret: 1 }] }],
    ['a missing warning flag', { items: [{ ...syntheticAgentTestCase(), is_synthetic_data_warning: false }] }],
    ['a non-object payload', { items: [{ ...syntheticAgentTestCase(), synthetic_payload: [] }] }],
    ['an extra context key', {
      items: [{ ...syntheticAgentTestCase(), assembly_context: { design_system_active: false, x: 1 } }],
    }],
    ['a non-list', { items: syntheticAgentTestCase() }],
  ])('contains a 200 list with %s as InvalidTestRunResponseError', async (_label, body) => {
    stubFetch(200, body);

    expect(await rejection(listTestCases('architect'))).toBeInstanceOf(InvalidTestRunResponseError);
  });

  it('creates a case with exactly the typed body', async () => {
    const created = syntheticAgentTestCase({ id: 202, name: 'New case', is_required: false });
    const fetchMock = stubFetch(201, created);
    const request = {
      agent_key: 'architect' as const,
      name: 'New case',
      synthetic_payload: { user_request: 'Synthetic ask' },
      assembly_context: { design_system_active: true },
      is_required: false,
    };

    await expect(createTestCase(request)).resolves.toEqual(created);

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/test-cases$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual(request);
    expect(Object.keys(JSON.parse(String(init.body)))).toEqual([
      'agent_key', 'name', 'synthetic_payload', 'assembly_context', 'is_required',
    ]);
  });

  it('retires one version with a bodyless DELETE', async () => {
    const retired = syntheticAgentTestCase({ is_active: false });
    const fetchMock = stubFetch(200, retired);

    await expect(retireTestCase(101)).resolves.toEqual(retired);

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/test-cases\/101$/);
    expect(init.method).toBe('DELETE');
    expect(init.body).toBeUndefined();
  });

  it('surfaces an ordered case 422 as a typed failure', async () => {
    const refused = syntheticInvalidTestCase([
      { field: 'is_active', code: 'last_required_case', message: 'The last required case cannot be retired.' },
    ]);
    stubFetch(422, refused);

    const error = await rejection(retireTestCase(101));

    expect(error).toBeInstanceOf(AgentTestApiError);
    expect((error as AgentTestApiError).failure).toEqual(refused);
  });
});

