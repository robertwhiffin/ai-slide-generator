/**
 * Pure model behind the "What's new in Tellr" popup.
 *
 * No `import.meta`, no DOM APIs: Playwright imports this file under Node.
 * Everything Vite-specific lives in releases.ts.
 */

export const WHATS_NEW_STORAGE_KEY = 'tellr-whats-new-last-seen';

export interface ReleaseNoteItem {
  title: string;
  body: string;
}

export interface ReleaseNotes {
  version: string;
  date: string;
  items: ReleaseNoteItem[];
}

const RELEASE_VERSION_RE = /^\d+\.\d+\.\d+$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** True for final versions only, e.g. '0.5.7' (not '0.5.7.dev1'). */
export function isReleaseVersion(v: string): boolean {
  return RELEASE_VERSION_RE.test(v);
}

/** Numeric per component: <0 if a is older, 0 if equal, >0 if a is newer. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function isRealDate(date: string): boolean {
  const m = DATE_RE.exec(date);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const t = new Date(Date.UTC(y, mo - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
}

/** Validate a parsed notes file. Throws an Error whose message names `fileStem`. */
export function parseReleaseNotes(raw: unknown, fileStem: string): ReleaseNotes {
  const fail = (why: string): never => {
    throw new Error(`Invalid release notes ${fileStem}.json: ${why}`);
  };
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return fail('expected an object');
  }
  const { version, date, items } = raw as Record<string, unknown>;

  if (typeof version !== 'string' || !isReleaseVersion(version)) {
    return fail(`version must look like X.Y.Z, got ${JSON.stringify(version)}`);
  }
  if (version !== fileStem) {
    return fail(`version ${JSON.stringify(version)} does not match the file name`);
  }
  if (typeof date !== 'string' || !isRealDate(date)) {
    return fail(`date must be a real YYYY-MM-DD date, got ${JSON.stringify(date)}`);
  }
  if (!Array.isArray(items)) {
    return fail('items must be an array');
  }
  items.forEach((item: unknown, i: number) => {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) {
      fail(`item ${i} must be an object`);
    }
    const { title, body } = item as Record<string, unknown>;
    if (typeof title !== 'string' || title.trim() === '') {
      fail(`item ${i} needs a non-empty title`);
    } else if (title.trim().endsWith('.')) {
      fail(`item ${i} title must not end with a period`);
    }
    if (typeof body !== 'string' || body.trim() === '') {
      fail(`item ${i} needs a non-empty body`);
    }
  });

  return raw as ReleaseNotes;
}

/** A new array, newest version first. */
export function sortNewestFirst(releases: ReleaseNotes[]): ReleaseNotes[] {
  return [...releases].sort((a, b) => compareVersions(b.version, a.version));
}

/** Newest version over ALL releases, empty ones included; null if none. */
export function newestVersion(releases: ReleaseNotes[]): string | null {
  let newest: string | null = null;
  for (const r of releases) {
    if (newest === null || compareVersions(r.version, newest) > 0) newest = r.version;
  }
  return newest;
}

/**
 * Versions with at least one item that are newer than `lastSeen`.
 * A null or non-release `lastSeen` (garbage, dev build) counts as nothing seen.
 */
export function unseenVersions(releases: ReleaseNotes[], lastSeen: string | null): Set<string> {
  const seen = lastSeen !== null && isReleaseVersion(lastSeen) ? lastSeen : null;
  const out = new Set<string>();
  for (const r of releases) {
    if (r.items.length === 0) continue;
    if (seen === null || compareVersions(r.version, seen) > 0) out.add(r.version);
  }
  return out;
}

/** '2026-11-14' -> 'November 2026', read as a UTC calendar date. */
export function formatReleaseMonth(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
}
