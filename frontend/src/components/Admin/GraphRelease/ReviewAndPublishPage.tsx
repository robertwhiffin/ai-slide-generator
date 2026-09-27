import { useState } from 'react';
import {
  RELEASE_NOTE_MAX_LENGTH,
  type AgentReadiness,
  type ChangedDefinitionPreview,
  type DraftReadiness,
  type JsonValue,
  type ReleaseFieldDiff,
  type ReleasePreviewResponse,
} from '../../../api/agentDefinitions';
import { lineDiff } from './lineDiff';
import {
  ROLE_LABELS,
  canPublish,
  publicationErrorMessage,
  publicationGapLabel,
  readinessStatusLabel,
  releaseNoteLength,
} from './reviewAndPublishState';
import { useReviewAndPublish } from './useReviewAndPublish';

type TabId = 'changes' | 'diff';

function jsonText(value: JsonValue): string {
  return JSON.stringify(value, null, 2);
}

function ReadinessList({ agent }: { agent: AgentReadiness | undefined }) {
  if (agent === undefined) return <p className="text-sm text-gray-500">No readiness reported for this role.</p>;
  if (agent.missing_required_case) return <p className="text-sm text-red-700">No active required test case</p>;
  if (agent.cases.length === 0) return <p className="text-sm text-gray-500">No required test cases listed.</p>;
  return (
    <ul aria-label="Required test cases" className="mt-1 space-y-1 text-sm text-gray-700">
      {agent.cases.map((item) => (
        <li key={item.test_case_id}>{`${item.test_case_name}: ${readinessStatusLabel(item.status)}`}</li>
      ))}
    </ul>
  );
}

function ChangesPanel({ preview }: { preview: ReleasePreviewResponse }) {
  if (preview.changed.length === 0) {
    return (
      <p className="text-sm text-gray-600">
        {`No Agent Definitions changed since Graph Version ${preview.active_release.version_number}.`}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {preview.changed.map((changed) => {
        const label = ROLE_LABELS[changed.agent_key];
        const headingId = `release-role-${changed.agent_key}`;
        return (
          <section
            key={changed.agent_key}
            aria-labelledby={headingId}
            className="rounded-lg border border-gray-200 bg-white p-4"
          >
            <h3 id={headingId} className="font-semibold text-gray-900">{label}</h3>
            <p className="mt-1 text-sm text-gray-600">
              {`Changed fields: ${changed.field_diffs.map((diff) => diff.field).join(', ')}`}
            </p>
            <ReadinessList agent={preview.readiness.agents.find((agent) => agent.agent_key === changed.agent_key)} />
          </section>
        );
      })}
      {preview.validation_issues.length > 0 && (
        <section aria-label="Validation issues" className="rounded-lg border border-red-200 bg-red-50 p-4">
          <h3 className="font-semibold text-red-800">Validation issues</h3>
          <ul className="mt-1 space-y-1 text-sm text-red-800">
            {preview.validation_issues.map((issue) => (
              <li key={`${issue.field}:${issue.code}`}>{publicationErrorMessage(issue)}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

const LINE_PREFIX = { same: '  ', removed: '- ', added: '+ ' } as const;
const LINE_CLASS = {
  same: 'text-gray-700',
  removed: 'bg-red-50 text-red-800',
  added: 'bg-green-50 text-green-800',
} as const;

function FieldDiffView({ diff }: { diff: ReleaseFieldDiff }) {
  if (diff.field === 'prompt_text' && typeof diff.published === 'string' && typeof diff.candidate === 'string') {
    return (
      <ul aria-label={diff.field} className="overflow-x-auto rounded border border-gray-200 font-mono text-xs">
        {lineDiff(diff.published, diff.candidate).map((line, index) => (
          <li key={index} data-kind={line.kind} className={`whitespace-pre ${LINE_CLASS[line.kind]}`}>
            {`${LINE_PREFIX[line.kind]}${line.text}`}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <pre
      data-testid={`release-diff-${diff.field}`}
      className="overflow-x-auto rounded border border-gray-200 bg-gray-50 p-2 font-mono text-xs"
    >
      {`${jsonText(diff.published)} → ${jsonText(diff.candidate)}`}
    </pre>
  );
}

function DiffPanel({ changed }: { changed: ChangedDefinitionPreview[] }) {
  if (changed.length === 0) return <p className="text-sm text-gray-600">No field differences.</p>;
  return (
    <div className="space-y-4">
      {changed.map((role) => (
        <section
          key={role.agent_key}
          aria-label={`${ROLE_LABELS[role.agent_key]} diff`}
          className="rounded-lg border border-gray-200 bg-white p-4"
        >
          <h3 className="font-semibold text-gray-900">{ROLE_LABELS[role.agent_key]}</h3>
          {role.field_diffs.map((diff) => (
            <div key={diff.field} className="mt-3">
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">{diff.field}</h4>
              <FieldDiffView diff={diff} />
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function ReloadButton({ onReload }: { onReload: () => void }) {
  return (
    <button
      type="button"
      onClick={onReload}
      className="mt-2 rounded border border-gray-300 bg-white px-3 py-1 text-sm font-medium text-gray-800 hover:bg-gray-50"
    >
      Reload preview
    </button>
  );
}

function NotReadyGaps({ gaps, readiness }: { gaps: Parameters<typeof publicationGapLabel>[0][]; readiness: DraftReadiness }) {
  return (
    <ul className="mt-1 list-disc pl-5 text-sm">
      {gaps.map((gap) => (
        <li key={`${gap.agent_key}:${gap.test_case_id ?? 'none'}:${gap.code}`}>{publicationGapLabel(gap, readiness)}</li>
      ))}
    </ul>
  );
}

/**
 * Review & Publish (#269, spec §13.2): the changed roles with their required-case
 * readiness, the field diffs, the release note and one Publish action. Readiness is
 * informational (C32); only the server's `publishable` enables Publish. Everything is
 * rendered as text. Release History arrives with #270.
 */
export function ReviewAndPublishPage() {
  const { state, setNote, publish, reloadPreview } = useReviewAndPublish();
  const [tab, setTab] = useState<TabId>('changes');
  const { preview } = state;
  const noteErrors = state.errors.filter((error) => error.field === 'release_note');
  const otherErrors = state.errors.filter((error) => error.field !== 'release_note');
  const reload = () => { void reloadPreview(); };
  const publishing = state.status === 'publishing';
  const noteBlank = state.note.trim() === '';
  const noteLength = releaseNoteLength(state.note);

  return (
    <div className="min-h-screen bg-gray-50">
      <div data-testid="release-review-page" className="mx-auto max-w-6xl p-6">
        <header className="mb-5">
          <a href="/admin" className="text-sm text-blue-600 hover:underline">Back to Admin</a>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">Review & Publish</h1>
        </header>

        {state.status === 'loading' && preview === null && (
          <p role="status" className="text-sm text-gray-500">Loading release preview…</p>
        )}

        {state.status === 'error' && (
          <div role="alert" className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <p>{state.errorMessage}</p>
            <ReloadButton onReload={reload} />
          </div>
        )}

        {state.published !== null && (
          <div
            data-testid="release-success-panel"
            role="status"
            className="mb-4 rounded border border-green-200 bg-green-50 p-3 text-sm text-green-900"
          >
            <p className="font-semibold">{`Published Graph Version ${state.published.release.version_number}`}</p>
            <p>{`The shared draft is now based on Graph Version ${state.published.draft.base_version_number}`}</p>
          </div>
        )}

        {state.stale !== null && (
          <div
            data-testid="release-stale-alert"
            role="alert"
            className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          >
            <p>
              {`The shared draft changed while you were reviewing: it is now at lock version ${state.stale.current_lock_version}`
                + ` (you reviewed lock version ${state.stale.expected_lock_version}).`
                + ` Graph Version ${state.stale.active_release.version_number} is active.`
                + ' Reload the preview to review the current draft. Your note is kept.'}
            </p>
            <ReloadButton onReload={reload} />
          </div>
        )}

        {state.notReady !== null && (
          <div
            data-testid="release-not-ready-panel"
            role="alert"
            className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          >
            <p>Publication was refused: these required approvals are missing.</p>
            <NotReadyGaps gaps={state.notReady.gaps} readiness={state.notReady.readiness} />
            <ReloadButton onReload={reload} />
          </div>
        )}

        {state.nothingToPublish !== null && (
          <div
            data-testid="release-nothing-panel"
            role="alert"
            className="mb-4 rounded border border-gray-200 bg-white p-3 text-sm text-gray-800"
          >
            <p>
              {`Nothing to publish: the shared draft matches Graph Version ${state.nothingToPublish.active_release.version_number}.`}
            </p>
            <ReloadButton onReload={reload} />
          </div>
        )}

        {otherErrors.length > 0 && (
          <div role="alert" className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <ul>
              {otherErrors.map((error) => (
                <li key={`${error.field}:${error.code}`}>{publicationErrorMessage(error)}</li>
              ))}
            </ul>
            <ReloadButton onReload={reload} />
          </div>
        )}

        {preview !== null && (
          <>
            <dl className="mb-4 flex flex-wrap gap-5 text-sm text-gray-600">
              <div data-testid="release-next-version">{`Next Graph Version: ${preview.next_version_number}`}</div>
              <div>{`Active: Graph Version ${preview.active_release.version_number}`}</div>
              <div>{`Draft base: Graph Version ${preview.draft.base_version_number}`}</div>
              <div>{`Lock version: ${preview.draft.lock_version}`}</div>
            </dl>

            <div role="tablist" aria-label="Release review" className="mb-4 flex gap-1 border-b border-gray-200">
              {([['changes', 'Changes & Approvals', 'release-changes-tab'], ['diff', 'Definition Diff', 'release-diff-tab']] as const)
                .map(([id, label, testId]) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    id={testId}
                    data-testid={testId}
                    aria-selected={tab === id}
                    aria-controls={`${testId}-panel`}
                    onClick={() => setTab(id)}
                    className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
                      tab === id ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-600'
                    }`}
                  >
                    {label}
                  </button>
                ))}
            </div>

            <div
              role="tabpanel"
              id={`${tab === 'changes' ? 'release-changes-tab' : 'release-diff-tab'}-panel`}
              aria-labelledby={tab === 'changes' ? 'release-changes-tab' : 'release-diff-tab'}
              className="mb-6"
            >
              {tab === 'changes' ? <ChangesPanel preview={preview} /> : <DiffPanel changed={preview.changed} />}
            </div>

            <section aria-label="Publish" className="rounded-lg border border-gray-200 bg-white p-4">
              <label htmlFor="release-note" className="block text-sm font-medium text-gray-700">Release note</label>
              <textarea
                id="release-note"
                data-testid="release-note-input"
                value={state.note}
                readOnly={publishing}
                onChange={(event) => setNote(event.target.value)}
                aria-invalid={noteErrors.length > 0 ? 'true' : undefined}
                aria-describedby={noteErrors.length > 0 ? 'release-note-error release-note-count' : 'release-note-count'}
                rows={3}
                className="mt-1 w-full rounded border border-gray-300 p-2 text-sm"
              />
              <p id="release-note-count" className="text-xs text-gray-500">
                {`${noteLength} / ${RELEASE_NOTE_MAX_LENGTH}`}
              </p>
              {noteErrors.length > 0 && (
                <p id="release-note-error" className="text-sm text-red-700">
                  {noteErrors.map(publicationErrorMessage).join(' ')}
                </p>
              )}
              {state.status === 'ready' && !preview.publishable && (
                <p className="mt-2 text-sm text-gray-700">This draft cannot be published yet.</p>
              )}
              {state.status === 'ready' && preview.publishable && noteBlank && (
                <p className="mt-2 text-sm text-gray-700">Enter a release note to publish.</p>
              )}
              <button
                type="button"
                data-testid="release-publish-button"
                disabled={!canPublish(state)}
                onClick={() => { void publish(); }}
                className="mt-3 rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {`Publish Graph Version ${preview.next_version_number}`}
              </button>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
