import { useId, useState } from 'react';
import type { CollaborationHistory, CollaborationReleaseGroup } from '@/services/api';

/**
 * The mixed-release collaboration warning and its change-provenance disclosure.
 *
 * DISPLAY VOCABULARY IS OWNED HERE (ruling F6). The collaboration-history API
 * deliberately emits no "Legacy", no "no graph release" and no "active" string —
 * a backend privacy test actively forbids the literal "Legacy" in the payload,
 * because display vocabulary does not belong in a privacy-scoped response. So
 * every word below is rendered from `graph_version === null`, and a legacy row
 * is never described as "active".
 *
 * ROWS COME FROM THE SERVER'S GROUPS, NEVER FROM THE ROOT BADGE. This component
 * is deliberately given no access to the conversation's own pinned version
 * (`GraphVersionStatus`'s `graphVersion`): labelling a contributor's change with
 * the root session's version is the exact defect issue #262 AC6 forbids, so the
 * per-row version can only come from `group.graph_version`.
 *
 * NO IDENTITY RECOVERY. The four group fields are the whole input. There is no
 * connected-user lookup, no root inference and no attempt to resolve
 * `actor_label` to a person; `Contributor N` is a response-local label that the
 * server reassigns per response.
 */

export const MIXED_RELEASE_WARNING_TEXT =
  'This shared deck has changes from multiple Graph Versions.';
export const LEGACY_RELEASE_LABEL = 'Legacy (no graph release)';
export const DISCLOSURE_LABEL = 'Change provenance';
/**
 * The provenance list's own accessible name.
 *
 * Deliberately NOT a superstring or substring of {@link DISCLOSURE_LABEL} or of
 * any row label: Playwright matches accessible names by case-insensitive
 * SUBSTRING while Testing Library's `name` is exact, so a nested name passes
 * Vitest and fails Playwright with `strict mode violation`. This epic has paid
 * for that twice.
 */
export const PROVENANCE_LIST_LABEL = 'Contributor releases';
/**
 * The single generic unavailable state. Every 404 from the history endpoint —
 * unknown id, unauthorized caller, guessed contributor id, missing or deleted
 * root, deckless root — is byte-identical, so exactly one wording covers them
 * all. It names no contributor, no version and no session, because any of those
 * would turn an indistinguishable 404 into a disclosure.
 */
export const HISTORY_UNAVAILABLE_TEXT = 'Collaboration history unavailable';

/** "Graph Version 3", or the legacy wording when there is no persisted release. */
export function releaseLabel(graphVersion: number | null): string {
  return graphVersion === null ? LEGACY_RELEASE_LABEL : `Graph Version ${graphVersion}`;
}

/**
 * One row's accessible name: actor, release, count.
 *
 * The timestamp is deliberately excluded — it is rendered inside the row as a
 * `<time>` element instead, so the row's NAME stays free of locale- and
 * timezone-dependent text that would differ between jsdom and Chromium.
 *
 * The trailing "N change(s)" token is what keeps row names mutually
 * non-substring: every name begins with "Contributor ", so one name can only be
 * a substring of another by being a suffix of it, and a distinct group cannot
 * produce a suffix-equal name.
 */
export function groupRowLabel(group: CollaborationReleaseGroup): string {
  const changes = `${group.mutation_count} change${group.mutation_count === 1 ? '' : 's'}`;
  return `${group.actor_label}, ${releaseLabel(group.graph_version)}, ${changes}`;
}

/**
 * `actor_label` is NOT unique — one actor spanning two releases keeps one label
 * across two groups — so the React key needs the release too.
 */
function groupKey(group: CollaborationReleaseGroup): string {
  return `${group.actor_label}|${group.graph_version ?? 'legacy'}`;
}

function formatMutationTime(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

export type MixedReleaseWarningProps = {
  /** Loaded collaboration evidence, or null when none is loaded. */
  history: CollaborationHistory | null;
  /** True when the load failed. One generic flag; see HISTORY_UNAVAILABLE_TEXT. */
  loadFailed: boolean;
  /**
   * Whether the conversation on screen is a persisted, server-authorized
   * session. The gate lives in this component rather than at the call site so
   * that it is directly testable: collaboration evidence describes a shared
   * deck that exists server-side, and a fresh local session has none.
   */
  isSessionPersisted: boolean;
};

export function MixedReleaseWarning({
  history,
  loadFailed,
  isSessionPersisted,
}: MixedReleaseWarningProps) {
  const listId = useId();
  const [isOpen, setIsOpen] = useState(false);

  if (!isSessionPersisted) {
    return null;
  }

  if (loadFailed) {
    return (
      <div
        data-testid="mixed-release-warning"
        className="border-b border-border bg-card px-3 py-1.5 text-xs text-muted-foreground"
      >
        <p role="status" data-testid="mixed-release-unavailable">
          {HISTORY_UNAVAILABLE_TEXT}
        </p>
      </div>
    );
  }

  if (history === null || history.groups.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="mixed-release-warning"
      className="flex flex-col gap-1 border-b border-border bg-card px-3 py-1.5 text-xs text-muted-foreground"
    >
      {history.mixed_release_warning && (
        <p role="status" data-testid="mixed-release-warning-text" className="text-foreground">
          {MIXED_RELEASE_WARNING_TEXT}
        </p>
      )}
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls={listId}
        data-testid="mixed-release-disclosure"
        onClick={() => setIsOpen((open) => !open)}
        className="self-start underline decoration-dotted underline-offset-2 hover:text-foreground"
      >
        {DISCLOSURE_LABEL}
      </button>
      {isOpen && (
        <ul
          id={listId}
          aria-label={PROVENANCE_LIST_LABEL}
          data-testid="mixed-release-provenance"
          className="flex flex-col gap-0.5"
        >
          {history.groups.map((group) => (
            <li
              key={groupKey(group)}
              aria-label={groupRowLabel(group)}
              data-testid="mixed-release-row"
            >
              <span>{groupRowLabel(group)}</span>
              {', '}
              <time dateTime={group.last_mutation_at}>
                {formatMutationTime(group.last_mutation_at)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
