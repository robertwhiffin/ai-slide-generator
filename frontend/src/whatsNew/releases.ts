import { parseReleaseNotes, sortNewestFirst, type ReleaseNotes } from './releaseNotes';

const FILES = import.meta.glob('./releases/*.json', { eager: true, import: 'default' });

/** Every bundled notes file, validated against its file name, newest first. */
export const RELEASES: ReleaseNotes[] = sortNewestFirst(
  Object.entries(FILES).map(([path, raw]) => {
    const stem = (path.split('/').pop() ?? '').replace(/\.json$/, '');
    return parseReleaseNotes(raw, stem);
  }),
);
