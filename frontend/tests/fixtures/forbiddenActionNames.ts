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
 * They are exempted by name rather than by loosening a stem, and each is removed from
 * the name before the stems are applied — so an exempt name cannot be used as a shield:
 * `Restore saved prompt and publish` still trips the guard.
 */
export const ALLOWED_ACTION_NAMES = [
  'Restore published Graph Version 1 prompt',
  'Restore saved prompt',
  'Restore retained values',
] as const;

/** True when `name` offers one of the actions this panel must never offer. */
export function forbidsActionName(name: string): boolean {
  const withoutAllowed = ALLOWED_ACTION_NAMES.reduce(
    (text, allowed) => text.split(allowed).join(' '),
    name,
  );
  return FORBIDDEN_ACTION_STEMS.test(withoutAllowed);
}
