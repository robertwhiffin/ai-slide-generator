/**
 * #260's guard on the Agent Definition panel: it may offer draft editing, and nothing
 * that executes, reviews, publishes, shows history, or rolls back.
 *
 * Both lanes read the rule from here so they cannot drift apart. The browser sweep
 * applies it to the composed `aria-label + textContent + title` of every control it
 * walks; the Vitest sweep applies it to each control's computed accessible name. Two
 * name sources, one rule.
 *
 * The stems are deliberately broad. A word-bounded `\bpublish(es|ing)?\b` spared
 * `Republish release`, `Unpublish draft`, `Publisher settings` and `Published versions`
 * — four plausible control names bought for one legitimate one, and weakened in exactly
 * the direction #264 and #266 extend this panel. `review` is the one stem that stays
 * narrow, and for a different reason: the node navigation renders `Build Reviewer`,
 * `Fix Reviewer` and `Deck Reviewer`, so a bare `review` stem is a false positive on
 * real control names rather than a missed one.
 */
export const FORBIDDEN_ACTION_STEMS =
  /\brun\b|approve|reject|review\s*&\s*publish|publish|history|rollback/i;

/**
 * The only control names this panel legitimately renders that carry a banned stem.
 *
 * They are exempted by exact whole name rather than by loosening a stem, so an exempt
 * name cannot be used as a shield: `Restore saved prompt and publish` still trips the
 * guard.
 *
 * #267 adds exactly its two run controls (C25/C38). The `run` stem stays, so every
 * other run control (`Run isolated test`, `View run 12`) is still banned, and
 * `Run published baseline` needs its exemption for `publish` as well.
 */
export const ALLOWED_ACTION_NAMES = [
  'Restore published Graph Version 1 prompt',
  'Restore saved prompt',
  'Restore retained values',
  'Run test case',
  'Run published baseline',
] as const;

/**
 * True when `name` offers one of the actions this panel must never offer.
 *
 * An exempt name is spared only when it is the **whole** name (whitespace normalized),
 * never as a substring: `Run test cases` and `Run test case now` still trip the guard
 * (#267 review m-5), and so does any exempt name with a banned suffix.
 */
export function forbidsActionName(name: string): boolean {
  const normalized = name.trim().replace(/\s+/g, ' ');
  if ((ALLOWED_ACTION_NAMES as readonly string[]).includes(normalized)) return false;
  return FORBIDDEN_ACTION_STEMS.test(normalized);
}
