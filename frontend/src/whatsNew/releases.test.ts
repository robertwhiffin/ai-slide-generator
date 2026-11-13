/**
 * releases: every bundled notes file in ./releases/, parsed and newest first
 * (plan docs/superpowers/plans/2026-11-13-whats-new-popup.md, Task 1).
 *
 * This PR adds no notes file, so apart from the shape check these pass
 * vacuously until the 0.5.7 bump PR adds the first one. From then on they are
 * the unit test that validates every notes file (spec, Part 2).
 *
 * Additions beyond the brief's Step 1 list:
 *  - The versions are exactly the file stems, with no duplicates. Length alone
 *    passes if a file is read under the wrong stem.
 *  - Every entry parses back to itself, so a malformed file goes red even if
 *    releases.ts stopped parsing and only cast the JSON.
 *
 * Sabotage notes (each turns this file red):
 *  - A temporary releases/0.5.7.json whose version is "0.5.8" (plan Step 5):
 *    RELEASES throws on import.
 *  - A valid notes file with `export const RELEASES = []`: "one entry per
 *    notes file" and "exactly the versions named by the notes files".
 *  - Two valid files, 0.5.6 and 0.5.7, with the final sortNewestFirst dropped
 *    from releases.ts (glob keys come oldest first in string order):
 *    "is sorted newest first".
 */
import { describe, it, expect } from 'vitest';
import { RELEASES } from './releases';
import { isReleaseVersion, parseReleaseNotes, sortNewestFirst } from './releaseNotes';

const NOTES_FILES = import.meta.glob('./releases/*.json');

/** './releases/0.5.7.json' -> '0.5.7' */
function stemOf(path: string): string {
  return (path.split('/').pop() ?? '').replace(/\.json$/, '');
}

describe('RELEASES', () => {
  it('is an array', () => {
    expect(Array.isArray(RELEASES)).toBe(true);
  });

  it('holds only final release versions', () => {
    for (const release of RELEASES) {
      expect(isReleaseVersion(release.version), release.version).toBe(true);
    }
  });

  it('is sorted newest first', () => {
    expect(RELEASES).toEqual(sortNewestFirst(RELEASES));
  });

  it('has one entry per notes file', () => {
    expect(Object.keys(NOTES_FILES).length).toBe(RELEASES.length);
  });

  it('has exactly the versions named by the notes files, with no duplicates', () => {
    const versions = RELEASES.map((r) => r.version);
    expect(new Set(versions).size).toBe(versions.length);
    expect([...versions].sort()).toEqual(Object.keys(NOTES_FILES).map(stemOf).sort());
  });

  it('holds only valid notes', () => {
    for (const release of RELEASES) {
      expect(parseReleaseNotes(release, release.version)).toStrictEqual(release);
    }
  });
});
