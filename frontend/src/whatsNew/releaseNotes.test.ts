/**
 * releaseNotes: the pure model behind the "What's new in Tellr" popup
 * (plan docs/superpowers/plans/2026-11-13-whats-new-popup.md, Task 1).
 *
 * Every expected value is a LITERAL from the brief, never rebuilt from the
 * module's own exports. Each rejected notes file differs from `valid()` in
 * exactly one field, so that field is the only reason it can be refused.
 *
 * Additions beyond the brief's Step 1 list (each one pins a rule the brief,
 * the Global Constraints or the Review Focus already states):
 *  - `2026-02-30` and `2026-02-29` are refused and `2028-02-29` is accepted:
 *    Step 3's "reject impossible dates" (a month regex alone passes `2026-13-01`).
 *  - Each bad item is tried alone and between two good items, so every item
 *    is checked, not just the first or the last.
 *  - `newestVersion` and `unseenVersions` get unsorted input and a
 *    `0.5.9`/`0.5.10` pair (Review Focus 3: badges land on the right releases).
 *  - `formatReleaseMonth` runs with the host clock in UTC, Los Angeles and
 *    Tokyo, because the brief's "guards against a shift into December 2025"
 *    only bites off UTC: UTC parse plus local format shifts west of UTC, and
 *    local parse plus UTC format shifts east of it.
 *  - `isReleaseVersion` and `WHATS_NEW_STORAGE_KEY` are pinned directly,
 *    because releases.test.ts and Tasks 2 and 4 rely on them.
 *
 * Sabotage notes (each turns the named tests red):
 *  - Compare versions as strings -> "orders numerically per component" and the
 *    0.5.10 cases of sortNewestFirst, newestVersion and unseenVersions.
 *  - Throw without the file stem in the message, or let a TypeError escape on
 *    `null` -> every "rejects ... naming the file" test.
 *  - Validate dates with a regex only -> 2026-02-30 and 2026-02-29.
 *  - Validate only `items[0]` -> the "between two good items" tests.
 *  - Skip `.trim()` on the title -> "a title of only spaces".
 *  - Sort in place -> "leaves the input array's order unchanged".
 *  - Skip empty releases in newestVersion -> "counts an empty release".
 *  - Count empty releases as unseen, or parse `0.5.7.dev3` as 0.5.7 ->
 *    the unseenVersions table.
 *  - Drop `timeZone: 'UTC'`, or build the date as local midnight ->
 *    formatReleaseMonth under Los Angeles or Tokyo.
 */
import { describe, it, expect, afterEach } from 'vitest';
import {
  WHATS_NEW_STORAGE_KEY,
  isReleaseVersion,
  compareVersions,
  parseReleaseNotes,
  sortNewestFirst,
  newestVersion,
  unseenVersions,
  formatReleaseMonth,
  type ReleaseNotes,
} from './releaseNotes';

/** The brief's 0.5.7 notes file, fresh on every call. */
const valid = () => ({
  version: '0.5.7',
  date: '2026-11-14',
  items: [{ title: 'Images in chat', body: 'Ask for an image of a monkey at a keyboard.' }],
});

const GOOD_ITEM = { title: 'Stop a generation', body: 'Press Esc to cancel mid-flow.' };

/** Release `version` with `n` items. Deterministic, so two calls are deep-equal. */
function R(version: string, n: number): ReleaseNotes {
  return {
    version,
    date: '2026-11-14',
    items: Array.from({ length: n }, (_, i) => ({
      title: `Feature ${i + 1} of ${version}`,
      body: `What feature ${i + 1} of ${version} does.`,
    })),
  };
}

/** The Error parseReleaseNotes throws for `raw` read from `<stem>.json`. */
function rejection(raw: unknown, stem: string): Error {
  let thrown: unknown = undefined;
  try {
    parseReleaseNotes(raw, stem);
  } catch (e) {
    thrown = e;
  }
  expect(thrown, `parseReleaseNotes accepted ${JSON.stringify(raw)} as ${stem}.json`).toBeInstanceOf(Error);
  return thrown as Error;
}

describe('WHATS_NEW_STORAGE_KEY', () => {
  it('is the Global Constraints key', () => {
    expect(WHATS_NEW_STORAGE_KEY).toBe('tellr-whats-new-last-seen');
  });
});

describe('isReleaseVersion', () => {
  it.each(['0.5.7', '0.5.10', '1.0.0', '10.20.30'])('accepts the final version %j', (v) => {
    expect(isReleaseVersion(v)).toBe(true);
  });

  it.each(['0.5.7.dev1', '0.5.7.dev3', '0.5.7rc1', '0.5', 'v0.5.7', ' 0.5.7', '0.5.7 ', '', 'abc'])(
    'refuses %j',
    (v) => {
      expect(isReleaseVersion(v)).toBe(false);
    },
  );
});

describe('parseReleaseNotes accepts', () => {
  it("the brief's 0.5.7 notes, returned unchanged", () => {
    const raw = valid();
    expect(parseReleaseNotes(raw, '0.5.7')).toStrictEqual({
      version: '0.5.7',
      date: '2026-11-14',
      items: [{ title: 'Images in chat', body: 'Ask for an image of a monkey at a keyboard.' }],
    });
    expect(raw).toStrictEqual(valid());
  });

  it('items: [] (a release with nothing user-facing)', () => {
    expect(parseReleaseNotes({ ...valid(), items: [] }, '0.5.7')).toStrictEqual({
      version: '0.5.7',
      date: '2026-11-14',
      items: [],
    });
  });

  it('several items, kept in file order', () => {
    const raw = { ...valid(), items: [GOOD_ITEM, ...valid().items] };
    expect(parseReleaseNotes(raw, '0.5.7')).toStrictEqual({
      version: '0.5.7',
      date: '2026-11-14',
      items: [
        { title: 'Stop a generation', body: 'Press Esc to cancel mid-flow.' },
        { title: 'Images in chat', body: 'Ask for an image of a monkey at a keyboard.' },
      ],
    });
  });

  it('a real leap day, 2028-02-29', () => {
    expect(parseReleaseNotes({ ...valid(), date: '2028-02-29' }, '0.5.7')).toStrictEqual({
      version: '0.5.7',
      date: '2028-02-29',
      items: [{ title: 'Images in chat', body: 'Ask for an image of a monkey at a keyboard.' }],
    });
  });
});

describe('parseReleaseNotes rejects, with an Error naming the file', () => {
  const REJECTED: Array<[string, unknown]> = [
    ['null', null],
    ['an array', [valid()]],
    ["version '0.5.8' in 0.5.7.json", { ...valid(), version: '0.5.8' }],
    ["date '14/11/2026'", { ...valid(), date: '14/11/2026' }],
    ["date '2026-13-01' (no month 13)", { ...valid(), date: '2026-13-01' }],
    ["date '2026-02-30' (no 30 February)", { ...valid(), date: '2026-02-30' }],
    ["date '2026-02-29' (2026 is not a leap year)", { ...valid(), date: '2026-02-29' }],
    ["items 'x'", { ...valid(), items: 'x' }],
  ];

  it.each(REJECTED)('%s', (_label, raw) => {
    expect(rejection(raw, '0.5.7').message).toMatch(/0\.5\.7/);
  });

  it("version '0.5.7.dev1' in 0.5.7.dev1.json (only final versions have notes)", () => {
    const raw = { ...valid(), version: '0.5.7.dev1' };
    expect(rejection(raw, '0.5.7.dev1').message).toMatch(/0\.5\.7\.dev1/);
  });

  const BAD_ITEMS: Array<[string, unknown]> = [
    ['a title of only spaces', { title: '   ', body: 'Ask for an image of a monkey at a keyboard.' }],
    ['an item with no body', { title: 'Images in chat' }],
    [
      "the title 'Images in chat.' (trailing period)",
      { title: 'Images in chat.', body: 'Ask for an image of a monkey at a keyboard.' },
    ],
  ];

  describe.each(BAD_ITEMS)('%s', (_label, bad) => {
    it('as the only item', () => {
      expect(rejection({ ...valid(), items: [bad] }, '0.5.7').message).toMatch(/0\.5\.7/);
    });

    it('between two good items', () => {
      const raw = { ...valid(), items: [GOOD_ITEM, bad, GOOD_ITEM] };
      expect(rejection(raw, '0.5.7').message).toMatch(/0\.5\.7/);
    });
  });
});

describe('compareVersions', () => {
  it('orders numerically per component, not as strings', () => {
    expect(compareVersions('0.5.10', '0.5.9')).toBeGreaterThan(0);
    expect(compareVersions('0.5.9', '0.5.10')).toBeLessThan(0);
    expect(compareVersions('1.0.0', '0.99.0')).toBeGreaterThan(0);
    expect(compareVersions('0.99.0', '1.0.0')).toBeLessThan(0);
  });

  it('is 0 for equal versions', () => {
    // `=== 0`, as the brief writes it, so a -0 also counts as equal.
    expect(compareVersions('0.5.7', '0.5.7') === 0).toBe(true);
  });

  it('is negative for an older version', () => {
    expect(compareVersions('0.5.6', '0.5.7')).toBeLessThan(0);
  });
});

describe('sortNewestFirst', () => {
  it("sorts newest first into a new array and leaves the input array's order unchanged", () => {
    const input = [R('0.5.9', 1), R('0.5.10', 2), R('0.5.7', 3)];
    const sorted = sortNewestFirst(input);

    expect(sorted.map((r) => r.version)).toEqual(['0.5.10', '0.5.9', '0.5.7']);
    expect(sorted).toStrictEqual([R('0.5.10', 2), R('0.5.9', 1), R('0.5.7', 3)]);
    expect(sorted).not.toBe(input);
    expect(input.map((r) => r.version)).toEqual(['0.5.9', '0.5.10', '0.5.7']);
    expect(input).toStrictEqual([R('0.5.9', 1), R('0.5.10', 2), R('0.5.7', 3)]);
  });
});

describe('newestVersion', () => {
  it('counts an empty release: [0.5.7 with items, 0.5.8 with items: []] gives 0.5.8', () => {
    expect(newestVersion([R('0.5.7', 2), R('0.5.8', 0)])).toBe('0.5.8');
  });

  it('does not depend on input order', () => {
    expect(newestVersion([R('0.5.8', 0), R('0.5.7', 2)])).toBe('0.5.8');
  });

  it('compares numerically: 0.5.10 is newer than 0.5.9', () => {
    expect(newestVersion([R('0.5.9', 1), R('0.5.10', 0), R('0.5.7', 1)])).toBe('0.5.10');
  });

  it('is null for no releases', () => {
    expect(newestVersion([])).toBeNull();
  });
});

describe('unseenVersions', () => {
  // 0.5.6, 0.5.7 and 0.5.8 have items; 0.5.9 is empty. Deliberately not in version order.
  const HISTORY = [R('0.5.8', 1), R('0.5.6', 2), R('0.5.9', 0), R('0.5.7', 1)];
  const ALL_WITH_ITEMS = ['0.5.6', '0.5.7', '0.5.8'];

  it.each<[string, string | null, string[]]>([
    ['null (nothing recorded)', null, ALL_WITH_ITEMS],
    ["'0.5.7'", '0.5.7', ['0.5.8']],
    ["'0.5.9' (the newest, empty, release)", '0.5.9', []],
    ["'abc' (garbage counts as nothing seen)", 'abc', ALL_WITH_ITEMS],
    ["'0.5.7.dev3' (a dev build counts as nothing seen)", '0.5.7.dev3', ALL_WITH_ITEMS],
  ])('last seen %s', (_label, lastSeen, expected) => {
    const unseen = unseenVersions(HISTORY, lastSeen);
    expect(unseen).toBeInstanceOf(Set);
    expect(unseen).toEqual(new Set(expected));
  });

  it('compares numerically: last seen 0.5.9 leaves 0.5.10 unseen, and 0.5.10 leaves nothing', () => {
    const releases = [R('0.5.9', 1), R('0.5.10', 1)];
    expect(unseenVersions(releases, '0.5.9')).toEqual(new Set(['0.5.10']));
    expect(unseenVersions(releases, '0.5.10')).toEqual(new Set());
  });
});

describe('formatReleaseMonth', () => {
  const ORIGINAL_TZ = process.env.TZ;
  afterEach(() => {
    if (ORIGINAL_TZ === undefined) delete process.env.TZ;
    else process.env.TZ = ORIGINAL_TZ;
  });

  /** Minutes behind UTC at local midnight on 2026-01-01, as getTimezoneOffset reports it. */
  const HOSTS: Array<[string, number]> = [
    ['UTC', 0],
    ['America/Los_Angeles', 480],
    ['Asia/Tokyo', -540],
  ];

  it.each(HOSTS)('reads the date as a UTC calendar date with the host clock in %s', (tz, offset) => {
    process.env.TZ = tz;
    // The switch took effect, so this host really is off UTC.
    expect(new Date(2026, 0, 1).getTimezoneOffset()).toBe(offset);

    expect(formatReleaseMonth('2026-11-14')).toBe('November 2026');
    // Not 'December 2025': the guard against a timezone shift.
    expect(formatReleaseMonth('2026-01-01')).toBe('January 2026');
  });
});
