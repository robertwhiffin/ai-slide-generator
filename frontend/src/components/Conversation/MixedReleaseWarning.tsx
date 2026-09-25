import { useId, useState } from 'react';
import type { CollaborationHistory, CollaborationReleaseGroup } from '@/services/api';

/**
 * The mixed-release collaboration warning and its change-provenance disclosure,
 * rendered on BOTH surfaces issue #262 AC5 names: the conversation surface
 * (beside the #261 pinned-version badge) and the collaboration surface (the
 * Share Deck dialog body).
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
 * server reassigns per response. Nothing is spread from the payload into the
 * DOM, so a server that later grew an identifying field could not leak through
 * an attribute either — `lets no server-added field reach the DOM or the
 * accessibility tree` asserts that over `outerHTML`, which includes the root's
 * own attributes, and over the computed accessible name.
 *
 * WHY THE TWO SURFACES USE DIFFERENT WORDING. The Share Deck dialog is an
 * overlay that leaves the conversation copy mounted behind it, so both
 * placements are in the DOM at once. Playwright matches accessible names by
 * case-insensitive SUBSTRING, so a suffixed name would make the conversation
 * copy's locator ambiguous. Wholly DISTINCT wording escapes that outright, and
 * `both surfaces stay independently addressable with the dialog open` measures
 * it rather than assuming it. Every RENDERED name is checked pairwise-non-nesting
 * by `no surface's accessible name nests inside another's`, which reads those
 * names back off the DOM rather than off an export of this table — an export
 * made that guard agree with this file by construction, so it could stay green
 * over a vocabulary it no longer described.
 */

const MIXED_RELEASE_WARNING_TEXT =
  'This shared deck has changes from multiple Graph Versions.';
const LEGACY_RELEASE_LABEL = 'Legacy (no graph release)';
/**
 * The single generic unavailable state. Every 404 from the history endpoint —
 * unknown id, unauthorized caller, guessed contributor id, missing or deleted
 * root, deckless root — is byte-identical, so exactly one wording covers them
 * all. It names no contributor, no version and no session, because any of those
 * would turn an indistinguishable 404 into a disclosure.
 */
const HISTORY_UNAVAILABLE_TEXT = 'Collaboration history unavailable';

type CollaborationSurface = 'conversation' | 'collaboration';

type SurfaceVocabulary = {
  /** Root test id, and the container every coexistence-safe locator scopes to. */
  testId: string;
  disclosureLabel: string;
  listLabel: string;
  /**
   * Whether this surface's warning is a live region.
   *
   * Only the conversation surface announces. Its warning can ARRIVE while the
   * user is reading, so `role="status"` is correct there. The dialog's copy is
   * static content the user just opened deliberately, and two simultaneous
   * identical live regions would announce the same sentence twice — a real
   * defect, not a cosmetic one. It also keeps `getByRole('status')`
   * unambiguous while both placements are mounted.
   */
  announce: boolean;
};

const SURFACE_VOCABULARY: Record<CollaborationSurface, SurfaceVocabulary> = {
  conversation: {
    testId: 'mixed-release-warning',
    disclosureLabel: 'Change provenance',
    listLabel: 'Contributor releases',
    announce: true,
  },
  collaboration: {
    testId: 'shared-deck-provenance',
    disclosureLabel: 'Who changed this deck',
    listLabel: 'Release history by contributor',
    announce: false,
  },
};

/** "Graph Version 3", or the legacy wording when there is no persisted release. */
function releaseLabel(graphVersion: number | null): string {
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
function groupRowLabel(group: CollaborationReleaseGroup): string {
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
  /** Which of AC5's two surfaces this instance is. Drives wording and test ids. */
  surface: CollaborationSurface;
};

export function MixedReleaseWarning({
  history,
  loadFailed,
  isSessionPersisted,
  surface,
}: MixedReleaseWarningProps) {
  const listId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const vocabulary = SURFACE_VOCABULARY[surface];

  if (!isSessionPersisted) {
    return null;
  }

  if (loadFailed) {
    return (
      <div
        data-testid={vocabulary.testId}
        className="border-b border-border bg-card px-3 py-1.5 text-xs text-muted-foreground"
      >
        <p
          {...(vocabulary.announce ? { role: 'status' } : {})}
          data-testid="mixed-release-unavailable"
        >
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
      data-testid={vocabulary.testId}
      className="flex flex-col gap-1 border-b border-border bg-card px-3 py-1.5 text-xs text-muted-foreground"
    >
      {history.mixed_release_warning && (
        <p
          {...(vocabulary.announce ? { role: 'status' } : {})}
          data-testid="mixed-release-warning-text"
          className="text-foreground"
        >
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
        {vocabulary.disclosureLabel}
      </button>
      {isOpen && (
        <ul
          id={listId}
          aria-label={vocabulary.listLabel}
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
