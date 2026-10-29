import { useEffect, useState } from 'react';
import {
  AgentDefinitionApiError,
  InvalidReleaseResponseError,
  adoptPackagedUpdate,
  getPackagedUpdate,
} from '../../../api/agentDefinitions';
import type { PackagedUpdate } from '../../../api/agentDefinitions';
import { FieldDiffView } from '../GraphRelease/FieldDiffView';
import { ROLE_LABELS } from '../GraphRelease/reviewAndPublishState';

const CONFIRM_ADOPT = 'Publish the shipped version as the next Graph Version? Pending draft edits are kept.';
const STALE_MESSAGE = 'The draft changed since you loaded it. Reload and try again.';
const INVALID_RESPONSE_MESSAGE = 'The adopt response was invalid. Reloading the workbench to show the current Graph Version.';

function reasonCopy(status: PackagedUpdate): string {
  switch (status.blocked_reason) {
    case 'hand_edited':
      return `Not applied automatically because these agents were edited here: ${
        status.hand_edited_agents.map((key) => ROLE_LABELS[key]).join(', ')}.`;
    case 'rollback':
      return 'Not applied automatically because the live release is a rollback.';
    case 'invalid':
      return 'The shipped version failed validation and was not applied.';
    default:
      return 'It will be applied automatically on the next restart.';
  }
}

function adoptErrorMessage(error: unknown): string {
  if (error instanceof InvalidReleaseResponseError) return INVALID_RESPONSE_MESSAGE;
  if (error instanceof AgentDefinitionApiError) {
    const payload = error.payload as { code?: string } | null;
    if (payload?.code === 'stale_publication') return STALE_MESSAGE;
    if (payload?.code === 'nothing_to_adopt') return 'There is no shipped version to adopt.';
    if (payload?.code === 'packaged_invalid') return 'The shipped version failed validation and was not applied.';
    return `Unable to adopt the shipped version (${error.status}).`;
  }
  return 'Unable to adopt the shipped version. Check your connection and try again.';
}

/**
 * Shows that a newer shipped Graph Configuration exists, with Review and Adopt. It
 * fetches its own status and renders nothing when none is available or the read fails.
 */
export function PackagedUpdateBadge({ onAdopted }: { onAdopted: () => void }) {
  const [status, setStatus] = useState<PackagedUpdate | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getPackagedUpdate().then(
      (response) => { if (active) setStatus(response); },
      () => { /* The badge is advisory: a failed read shows nothing. */ },
    );
    return () => { active = false; };
  }, []);

  if (!status || !status.available) return null;

  const adopt = async () => {
    if (!window.confirm(CONFIRM_ADOPT)) return;
    setAdopting(true);
    setError(null);
    try {
      await adoptPackagedUpdate(status.lock_version);
      onAdopted();
    } catch (adoptError: unknown) {
      setError(adoptErrorMessage(adoptError));
      // A malformed response may follow a publish that did happen: reload to show the truth.
      if (adoptError instanceof InvalidReleaseResponseError) onAdopted();
    } finally {
      setAdopting(false);
    }
  };

  return (
    <section
      aria-label="Shipped version"
      className="w-full rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900"
    >
      <h3 className="font-semibold">A newer shipped version is available</h3>
      <p className="mt-1">{reasonCopy(status)}</p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => setReviewing((open) => !open)}
          aria-expanded={reviewing}
          className="rounded border border-blue-300 bg-white px-3 py-1 font-medium"
        >
          Review changes
        </button>
        <button
          type="button"
          onClick={() => { void adopt(); }}
          disabled={status.blocked_reason === 'invalid' || adopting}
          className="rounded bg-blue-700 px-3 py-1 font-medium text-white disabled:opacity-50"
        >
          Adopt shipped version
        </button>
      </div>
      {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
      {reviewing && (
        <div className="mt-3 space-y-3">
          {status.diffs.map((diff) => (
            <div key={diff.agent_key}>
              <h4 className="font-medium">{ROLE_LABELS[diff.agent_key]}</h4>
              <div className="mt-1 space-y-2">
                {diff.field_diffs.map((fieldDiff) => (
                  <div key={fieldDiff.field}>
                    <p className="font-mono text-xs">{fieldDiff.field}</p>
                    <FieldDiffView
                      field={fieldDiff.field}
                      before={fieldDiff.published}
                      after={fieldDiff.candidate}
                      testIdPrefix="packaged-diff"
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
