import React from 'react';

// Only https:// URLs are linked. No other scheme (javascript:, http:, data:) ever becomes an href.
const URL_PATTERN = /https:\/\/[^\s<>"'`]+/g;
const TRAILING_PUNCTUATION = /[.,;)]+$/;

/**
 * Split text into plain strings and `<a>` elements for each https URL.
 *
 * Builds React elements only (never an HTML string), so nothing in `text` can inject markup.
 * Trailing `.,;)` is kept outside the link.
 */
export function linkifyText(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let index = 0;

  for (const match of text.matchAll(URL_PATTERN)) {
    const start = match.index ?? 0;
    let url = match[0];
    url = url.replace(TRAILING_PUNCTUATION, '');
    if (url === 'https://') continue;

    if (start > cursor) {
      nodes.push(text.slice(cursor, start));
    }
    nodes.push(
      <a
        key={`a${index++}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="underline underline-offset-2 break-all"
      >
        {url}
      </a>,
    );
    cursor = start + url.length;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes;
}
