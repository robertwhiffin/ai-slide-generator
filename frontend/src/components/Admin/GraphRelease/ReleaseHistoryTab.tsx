import {
  AGENT_KEYS,
  RELEASE_NOTE_MAX_LENGTH,
  type AgentComparison,
  type DraftFieldError,
  type ReleaseComparisonResponse,
  type ReleaseDetailResponse,
  type ReleaseHistoryEntry,
  type RollbackPreviewResponse,
} from '../../../api/agentDefinitions';
import { FieldDiffView } from './FieldDiffView';
import { formatInstant, jsonText } from './releaseText';
import {
  DRAFT_EFFECT_LABELS,
  EVIDENCE_KIND_LABELS,
  ROLE_LABELS,
  releaseNoteLength,
  rollbackBlockedMessage,
  rollbackErrorMessage,
  runVerdictLabel,
  type HistorySlice,
  type InspectionSlice,
  type RollbackSlice,
} from './reviewAndPublishState';

/** Correction 3: fixed accessible names, scoped by row; the version is in the row heading. */
export const INSPECT_VERSION_NAME = 'Inspect this version';
export const ROLL_BACK_VERSION_NAME = 'Roll back to this version';

export interface ReleaseHistoryTabProps {
  history: HistorySlice;
  inspection: InspectionSlice;
  rollback: RollbackSlice;
  /** The page reducer's `canConfirmRollback`. */
  canConfirm: boolean;
  onReloadHistory: () => void;
  onInspect: (versionNumber: number) => void;
  onOpenRollback: (versionNumber: number) => void;
  onRollbackNoteChange: (note: string) => void;
  onConfirmRollback: () => void;
  onCancelRollback: () => void;
  onReloadRollback: () => void;
}

function roleList(keys: readonly (keyof typeof ROLE_LABELS)[]): string {
  return keys.map((key) => ROLE_LABELS[key]).join(', ');
}

function IssueList({ issues, label }: { issues: DraftFieldError[]; label: string }) {
  if (issues.length === 0) return null;
  return (
    <ul aria-label={label} className="mt-1 list-disc pl-5 text-sm">
      {issues.map((issue) => (
        <li key={`${issue.field}:${issue.code}`}>{rollbackErrorMessage(issue)}</li>
      ))}
    </ul>
  );
}

function HistoryRow({
  entry,
  onInspect,
  onOpenRollback,
}: {
  entry: ReleaseHistoryEntry;
  onInspect: (versionNumber: number) => void;
  onOpenRollback: (versionNumber: number) => void;
}) {
  const version = entry.version_number;
  const headingId = `release-history-row-${version}-heading`;
  return (
    <li
      data-testid={`release-history-row-${version}`}
      aria-labelledby={headingId}
      className="rounded-lg border border-gray-200 bg-white p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="font-semibold text-gray-900">{`Graph Version ${version}`}</h3>
        {entry.is_active && (
          <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800">Active</span>
        )}
        {entry.restored_from !== null && (
          <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800">
            {`Restores Graph Version ${entry.restored_from.version_number}`}
          </span>
        )}
      </div>
      <dl className="mt-2 grid gap-1 text-sm text-gray-700">
        <div>{`Published by ${entry.published_by} at ${formatInstant(entry.published_at)}`}</div>
        <div>
          {`Effective from ${formatInstant(entry.effective_from)} to ${
            entry.effective_to === null ? 'now' : formatInstant(entry.effective_to)}`}
        </div>
        <div>
          {entry.previous === null
            ? 'Predecessor: none'
            : `Predecessor: Graph Version ${entry.previous.version_number}`}
        </div>
        <div>{`Changed roles: ${roleList(entry.changed_agents)}`}</div>
        {entry.restored_by.length > 0 && (
          <div>{`Restored as ${entry.restored_by.map((ref) => `Graph Version ${ref.version_number}`).join(', ')}`}</div>
        )}
        <div>{`Note: ${entry.release_note}`}</div>
      </dl>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          aria-describedby={headingId}
          onClick={() => onInspect(version)}
          className="rounded border border-gray-300 bg-white px-3 py-1 text-sm font-medium text-gray-800 hover:bg-gray-50"
        >
          {INSPECT_VERSION_NAME}
        </button>
        {!entry.is_active && (
          <button
            type="button"
            aria-describedby={headingId}
            onClick={() => onOpenRollback(version)}
            className="rounded border border-amber-300 bg-white px-3 py-1 text-sm font-medium text-amber-800 hover:bg-amber-50"
          >
            {ROLL_BACK_VERSION_NAME}
          </button>
        )}
      </div>
    </li>
  );
}

function ComparisonView({ comparison }: { comparison: ReleaseComparisonResponse }) {
  const active = comparison.active_release.version_number;
  return (
    <section
      data-testid="release-comparison"
      aria-label="Comparison with the active release"
      className="mt-4 space-y-3"
    >
      <h4 className="font-semibold text-gray-900">
        {`Graph Version ${comparison.release.version_number} against the active Graph Version ${active}`}
      </h4>
      {comparison.agents.map((agent) => (
        <section
          key={agent.agent_key}
          aria-label={`${ROLE_LABELS[agent.agent_key]} comparison`}
          className="rounded border border-gray-200 p-3"
        >
          <h5 className="text-sm font-semibold text-gray-900">{ROLE_LABELS[agent.agent_key]}</h5>
          {agent.field_diffs.length === 0 ? (
            <p className="text-sm text-gray-600">Same as active</p>
          ) : agent.field_diffs.map((diff) => (
            <div key={diff.field} className="mt-2">
              <h6 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">{diff.field}</h6>
              <FieldDiffView
                field={diff.field}
                before={diff.active}
                after={diff.historical}
                testIdPrefix="release-comparison-diff"
              />
            </div>
          ))}
        </section>
      ))}
    </section>
  );
}

function DetailView({ detail, comparison }: { detail: ReleaseDetailResponse; comparison: ReleaseComparisonResponse }) {
  const version = detail.release.version_number;
  return (
    <section
      data-testid="release-history-detail"
      aria-label={`Graph Version ${version} details`}
      className="mb-4 rounded-lg border border-gray-200 bg-white p-4"
    >
      <h3 className="font-semibold text-gray-900">{`Graph Version ${version} details`}</h3>
      <ul aria-label="Definitions" className="mt-2 space-y-2 text-sm text-gray-700">
        {AGENT_KEYS.map((agentKey) => {
          const definition = detail.definitions[agentKey];
          const prompt = definition.content.prompt_text;
          return (
            <li key={agentKey} data-testid={`release-definition-${agentKey}`}>
              <p className="font-medium text-gray-900">
                {`${ROLE_LABELS[agentKey]}: revision ${definition.agent_definition_revision_id}`}
              </p>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-gray-50 p-2 font-mono text-xs">
                {typeof prompt === 'string' ? prompt : jsonText(definition.content)}
              </pre>
            </li>
          );
        })}
      </ul>
      <h4 className="mt-4 font-semibold text-gray-900">Evidence</h4>
      {detail.evidence.length === 0 ? (
        <p className="text-sm text-gray-600">No linked test runs.</p>
      ) : (
        <ul aria-label="Evidence" className="mt-1 space-y-1 text-sm text-gray-700">
          {detail.evidence.map((item) => (
            <li key={item.agent_test_run_id} data-testid={`release-evidence-${item.agent_test_run_id}`}>
              {[
                `${ROLE_LABELS[item.agent_key]}, test case ${item.test_case_id} (version ${item.test_case_version})`,
                EVIDENCE_KIND_LABELS[item.evidence_kind],
                item.source === null ? 'no source' : `from Graph Version ${item.source.version_number}`,
                runVerdictLabel(item.verdict),
              ].join(' · ')}
            </li>
          ))}
        </ul>
      )}
      <ComparisonView comparison={comparison} />
    </section>
  );
}

function MappingList({ agents, preview }: { agents: AgentComparison[]; preview: RollbackPreviewResponse }) {
  return (
    <ul aria-label="Mappings" className="mt-2 space-y-1 text-sm text-gray-700">
      {agents.map((agent) => (
        <li key={agent.agent_key}>
          {`${ROLE_LABELS[agent.agent_key]}: revision ${agent.historical_revision_id}`
            + (agent.same_revision ? ' (same as active)' : ` (active: revision ${agent.active_revision_id})`)
            + ` · Draft: ${DRAFT_EFFECT_LABELS[preview.draft_effect[agent.agent_key]]}`}
        </li>
      ))}
    </ul>
  );
}

function RollbackPanel({
  rollback,
  canConfirm,
  onRollbackNoteChange,
  onConfirmRollback,
  onCancelRollback,
  onReloadRollback,
}: Pick<ReleaseHistoryTabProps,
  'rollback' | 'canConfirm' | 'onRollbackNoteChange' | 'onConfirmRollback' | 'onCancelRollback' | 'onReloadRollback'>) {
  const { preview } = rollback;
  const rollingBack = rollback.status === 'rollingBack';
  const noteErrors = rollback.errors.filter((error) => error.field === 'release_note');
  const otherErrors = rollback.errors.filter((error) => error.field !== 'release_note');
  return (
    <section
      data-testid="rollback-preview"
      aria-label="Rollback"
      className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-gray-800"
    >
      <h3 className="font-semibold text-gray-900">{`Roll back to Graph Version ${rollback.versionNumber ?? ''}`}</h3>

      {rollback.status === 'previewLoading' && (
        <p role="status" className="text-gray-600">Loading rollback preview…</p>
      )}

      {rollback.status === 'error' && (
        <p role="alert" className="mt-2 text-red-800">{rollback.errorMessage}</p>
      )}

      {rollback.stale !== null && (
        <div data-testid="rollback-stale-alert" role="alert" className="mt-2 rounded border border-amber-300 bg-white p-3">
          <p>
            {`The shared draft changed: it is now at lock version ${rollback.stale.current_lock_version}`
              + ` (the rollback preview read lock version ${rollback.stale.expected_lock_version}).`
              + ` Graph Version ${rollback.stale.active_release.version_number} is active.`
              + ' Reload the preview to review the rollback again. Your note is kept.'}
          </p>
          <button
            type="button"
            onClick={onReloadRollback}
            className="mt-2 rounded border border-gray-300 bg-white px-3 py-1 text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            Reload preview
          </button>
        </div>
      )}

      {preview !== null && (
        <>
          <p data-testid="rollback-lineage" className="mt-2 font-medium">
            {`Graph Version ${preview.next_version_number} will restore Graph Version ${preview.source.version_number}`
              + ` (predecessor Graph Version ${preview.active_release.version_number}).`}
          </p>
          <MappingList agents={preview.agents} preview={preview} />
          <p className="mt-2">{`Evidence links restored: ${preview.evidence.length}`}</p>
          {preview.warnings.length > 0 && (
            <div data-testid="rollback-warnings" className="mt-2 rounded border border-amber-300 bg-white p-3">
              <p>These restored endpoints did not resolve. The rollback can still go ahead.</p>
              <IssueList issues={preview.warnings} label="Endpoint warnings" />
            </div>
          )}
        </>
      )}

      {rollback.blocked !== null && (
        <div data-testid="rollback-blocked-panel" role="alert" className="mt-2 rounded border border-red-200 bg-red-50 p-3 text-red-800">
          <p>{rollbackBlockedMessage(rollback.blocked)}</p>
          <IssueList issues={rollback.blocked.issues} label="Rollback issues" />
          <p className="mt-1">The active release is unchanged.</p>
        </div>
      )}

      {otherErrors.length > 0 && (
        <div role="alert" className="mt-2 text-red-800">
          <IssueList issues={otherErrors} label="Refused rollback" />
        </div>
      )}

      {preview !== null && (
        <div className="mt-3">
          <label htmlFor="rollback-note" className="block font-medium text-gray-700">Rollback note</label>
          <textarea
            id="rollback-note"
            data-testid="rollback-note-input"
            value={rollback.note}
            readOnly={rollingBack}
            onChange={(event) => onRollbackNoteChange(event.target.value)}
            aria-invalid={noteErrors.length > 0 ? 'true' : undefined}
            aria-describedby={noteErrors.length > 0 ? 'rollback-note-error rollback-note-count' : 'rollback-note-count'}
            rows={2}
            className="mt-1 w-full rounded border border-gray-300 p-2 text-sm"
          />
          <p id="rollback-note-count" className="text-xs text-gray-500">
            {`${releaseNoteLength(rollback.note)} / ${RELEASE_NOTE_MAX_LENGTH}`}
          </p>
          {noteErrors.length > 0 && (
            <p id="rollback-note-error" className="text-red-700">{noteErrors.map(rollbackErrorMessage).join(' ')}</p>
          )}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          data-testid="rollback-confirm-button"
          disabled={!canConfirm}
          onClick={onConfirmRollback}
          className="rounded bg-amber-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          Confirm rollback
        </button>
        <button
          type="button"
          data-testid="rollback-cancel-button"
          disabled={rollingBack}
          onClick={onCancelRollback}
          className="rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-800 disabled:cursor-not-allowed"
        >
          Cancel rollback
        </button>
      </div>
    </section>
  );
}

/**
 * Release History (#270, spec §13.2): every Graph Version newest first, one inspection,
 * and one rollback at a time. It owns no reducer, request counter or write gate: every
 * control dispatches into the Review & Publish page's one reducer through its props.
 * Everything is rendered as text.
 */
export function ReleaseHistoryTab(props: ReleaseHistoryTabProps) {
  const { history, inspection, rollback } = props;
  return (
    <div className="space-y-4">
      {rollback.status === 'restored' && rollback.restored !== null && (
        <div
          data-testid="rollback-success-panel"
          role="status"
          className="rounded border border-green-200 bg-green-50 p-3 text-sm text-green-900"
        >
          <p className="font-semibold">
            {`Graph Version ${rollback.restored.release.version_number} restores Graph Version ${rollback.restored.restored_from.version_number}`}
          </p>
          <p>{`The shared draft is now based on Graph Version ${rollback.restored.draft.base_version_number}`}</p>
        </div>
      )}

      {rollback.status !== 'closed' && rollback.status !== 'restored' && <RollbackPanel {...props} />}

      {inspection.status === 'loading' && (
        <p role="status" className="text-sm text-gray-500">{`Loading Graph Version ${inspection.versionNumber}…`}</p>
      )}
      {inspection.errorMessage !== null && (
        <p role="alert" className="text-sm text-red-800">{inspection.errorMessage}</p>
      )}
      {inspection.status === 'shown' && inspection.detail !== null && inspection.comparison !== null && (
        <DetailView detail={inspection.detail} comparison={inspection.comparison} />
      )}

      {history.status === 'loading' && history.list === null && (
        <p role="status" className="text-sm text-gray-500">Loading release history…</p>
      )}
      {history.status === 'error' && (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <p>{history.errorMessage}</p>
          <button
            type="button"
            onClick={props.onReloadHistory}
            className="mt-2 rounded border border-gray-300 bg-white px-3 py-1 text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            Reload versions
          </button>
        </div>
      )}
      {history.list !== null && (
        <ol aria-label="Graph Versions" className="space-y-3">
          {history.list.releases.map((entry) => (
            <HistoryRow
              key={entry.version_number}
              entry={entry}
              onInspect={props.onInspect}
              onOpenRollback={props.onOpenRollback}
            />
          ))}
        </ol>
      )}
    </div>
  );
}
