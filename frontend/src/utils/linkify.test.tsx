/**
 * linkifyText: turns `https://` URLs in plain chat text into new-tab anchors, and nothing else.
 *
 * Gateway MCP Task 7. A Gateway sign-in notice ("To use LakeDraw, sign in here: <url> — then ask
 * again.") must be clickable in chat. Only `https://` is linked; trailing `.,;)` is not part of the
 * link; no other HTML is ever produced (React escapes the text, never innerHTML).
 */
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { linkifyText } from './linkify';

// The measured LakeDraw sign-in sentence, verbatim (the backend's sign-in copy with the real URL).
const SENTENCE =
  'To use LakeDraw, sign in here: https://fevm-db-tellr-dev-workspace.cloud.databricks.com/mcp-service-login?name=db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw&o=7474645249186749 — then ask again.';
const SIGN_IN_URL =
  'https://fevm-db-tellr-dev-workspace.cloud.databricks.com/mcp-service-login?name=db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw&o=7474645249186749';

function renderText(text: string) {
  const { container } = render(<div data-testid="out">{linkifyText(text)}</div>);
  const out = container.querySelector('[data-testid="out"]') as HTMLElement;
  return { out, anchors: Array.from(out.querySelectorAll('a')) };
}

describe('linkifyText', () => {
  it('returns an array of nodes', () => {
    expect(Array.isArray(linkifyText('no links here'))).toBe(true);
    expect(Array.isArray(linkifyText(SENTENCE))).toBe(true);
  });

  it('turns the LakeDraw sign-in sentence into exactly one anchor whose href is the whole URL', () => {
    expect(SENTENCE.includes(SIGN_IN_URL)).toBe(true); // guard on the fixture itself

    const { out, anchors } = renderText(SENTENCE);

    expect(anchors).toHaveLength(1);
    const a = anchors[0];
    const href = a.getAttribute('href') ?? '';
    expect(href).toBe(SIGN_IN_URL);
    expect(href.endsWith('&o=7474645249186749')).toBe(true);
    expect(a.textContent).toBe(SIGN_IN_URL);
    expect(a.getAttribute('target')).toBe('_blank');
    expect(a.getAttribute('rel')).toBe('noopener noreferrer');

    // No text is lost or added around the link.
    expect(out.textContent).toBe(SENTENCE);
    expect(a.nextSibling?.textContent).toBe(' — then ask again.');
  });

  it.each(['.', ',', ';', ')'])('keeps a trailing "%s" outside the link', (p) => {
    const text = `See https://example.com/docs/page${p} next`;
    const { out, anchors } = renderText(text);

    expect(anchors).toHaveLength(1);
    expect(anchors[0].getAttribute('href')).toBe('https://example.com/docs/page');
    expect(anchors[0].textContent).toBe('https://example.com/docs/page');
    expect(anchors[0].nextSibling?.textContent?.startsWith(p)).toBe(true);
    expect(out.textContent).toBe(text);
  });

  it('keeps a run of trailing punctuation outside the link, at the end of the text', () => {
    const text = '(see https://example.com/x).';
    const { out, anchors } = renderText(text);

    expect(anchors).toHaveLength(1);
    expect(anchors[0].getAttribute('href')).toBe('https://example.com/x');
    expect(anchors[0].nextSibling?.textContent).toBe(').');
    expect(out.textContent).toBe(text);
  });

  it('keeps punctuation that sits INSIDE a URL', () => {
    const text = 'Open https://example.com/a.b/c,d?q=1;2 now';
    const { anchors } = renderText(text);

    expect(anchors).toHaveLength(1);
    expect(anchors[0].getAttribute('href')).toBe('https://example.com/a.b/c,d?q=1;2');
  });

  it('links every https URL in the text, each with a React key', () => {
    const text = 'First https://one.example.com/1 then https://two.example.com/2.';
    const { out, anchors } = renderText(text);

    expect(anchors.map((a) => a.getAttribute('href'))).toEqual([
      'https://one.example.com/1',
      'https://two.example.com/2',
    ]);
    expect(out.textContent).toBe(text);

    // Elements in the returned array carry keys (no React "unique key" warning in chat).
    const elements = linkifyText(text).filter(React.isValidElement);
    expect(elements).toHaveLength(2);
    const keys = elements.map((el) => el.key);
    expect(keys.every((k) => k !== null && k !== undefined)).toBe(true);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('leaves a javascript: URL as plain text', () => {
    const text = 'click javascript:alert(1) now';
    const { out, anchors } = renderText(text);

    expect(anchors).toHaveLength(0);
    expect(out.textContent).toBe(text);
  });

  it('leaves an http:// URL as plain text', () => {
    const text = 'visit http://example.com/insecure today';
    const { out, anchors } = renderText(text);

    expect(anchors).toHaveLength(0);
    expect(out.textContent).toBe(text);
  });

  it('produces no other HTML: markup in the text stays literal', () => {
    const text = '<b>bold</b> <img src=x onerror=alert(1)> and https://example.com/ok';
    const { out, anchors } = renderText(text);

    expect(out.querySelector('b')).toBeNull();
    expect(out.querySelector('img')).toBeNull();
    expect(anchors).toHaveLength(1);
    expect(anchors[0].getAttribute('href')).toBe('https://example.com/ok');
    // The only element produced is the anchor.
    expect(Array.from(out.querySelectorAll('*')).map((el) => el.tagName)).toEqual(['A']);
    expect(out.textContent).toBe(text);
  });

  it('returns text without URLs unchanged and without anchors', () => {
    const text = 'Nothing to link here.\nSecond line.';
    const { out, anchors } = renderText(text);

    expect(anchors).toHaveLength(0);
    expect(out.textContent).toBe(text);
  });
});
