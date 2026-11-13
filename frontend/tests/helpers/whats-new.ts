/**
 * Release-notes facts for E2E, read from the bundled notes files on disk.
 *
 * Node-side only: it does not import `src/whatsNew/releases.ts`, which uses
 * `import.meta.glob` (a Vite feature that does not exist under Node).  It reads
 * `src/whatsNew/releases/<X.Y.Z>.json` directly instead.
 */
import { readdirSync, readFileSync } from 'node:fs';
import {
  WHATS_NEW_STORAGE_KEY,
  compareVersions,
  isReleaseVersion,
} from '../../src/whatsNew/releaseNotes';

const RELEASES_DIR = new URL('../../src/whatsNew/releases/', import.meta.url);

/** Versions of every `<X.Y.Z>.json` notes file, newest first. */
function bundledVersions(): string[] {
  return readdirSync(RELEASES_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -'.json'.length))
    .filter(isReleaseVersion) // compareVersions returns NaN on anything else
    .sort((a, b) => compareVersions(b, a));
}

/**
 * The newest version over ALL notes files, including ones with no items.  This
 * matches what the app records when the popup is dismissed.  Null when none.
 */
export function newestReleaseNotesVersion(): string | null {
  return bundledVersions()[0] ?? null;
}

/** True when at least one notes file has at least one item (the popup can open). */
export function hasReleaseNotesWithItems(): boolean {
  return bundledVersions().some((v) => {
    const raw = JSON.parse(readFileSync(new URL(`${v}.json`, RELEASES_DIR), 'utf8')) as {
      items?: unknown[];
    };
    return Array.isArray(raw.items) && raw.items.length > 0;
  });
}

/** localStorage entries marking every bundled release as seen; [] when none. */
export function whatsNewSeenStorage(): { name: string; value: string }[] {
  const newest = newestReleaseNotesVersion();
  return newest === null ? [] : [{ name: WHATS_NEW_STORAGE_KEY, value: newest }];
}
