import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MCPDiscovery } from './MCPDiscovery';

const DISCOVER_SUFFIX = '/api/tools/discover/mcp';
const EMPTY_STATE = 'No MCP connections available.';

// The backend's consent_message(oauth_client_id="tellr-app-1234"), verbatim.
const CONSENT = [
  "Tellr can't do this on your behalf yet: your sign-in to this app is missing a permission it needs.",
  '',
  'There are two possible causes:',
  '1. The app itself hasn\'t been given the permission. A workspace admin fixes this by running tellr.update() for this app.',
  '2. You approved this app before it needed this permission. To approve it again:',
  '   a. Run: databricks api delete /api/2.0/oauth-app-integrations/tellr-app-1234/user-consent/me',
  "   b. Clear this site's data in your browser, or open the app in a private window.",
  '   c. Reload the app and approve the new permissions when asked.',
].join('\n');

// Match an element's own text exactly, with no whitespace collapsing, so the
// newlines must reach the DOM as one text block.
const exact = { normalizer: (s: string) => s };

function reply(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: vi.fn().mockResolvedValue(body),
  };
}

function unparseableReply(status: number) {
  return {
    ok: false,
    status,
    statusText: 'Bad Gateway',
    json: vi.fn().mockRejectedValue(new SyntaxError('Unexpected token < in JSON at position 0')),
  };
}

function stubDiscover(response: unknown) {
  const mock = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).endsWith(DISCOVER_SUFFIX)) return response;
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function renderDiscovery() {
  return render(
    <MCPDiscovery
      onSelect={vi.fn()}
      onPreview={vi.fn()}
      onClose={vi.fn()}
      existingTools={[]}
    />,
  );
}

function hasPreLine(el: HTMLElement): boolean {
  const styled = el.closest<HTMLElement>('.whitespace-pre-line, [style*="pre-line"]');
  return styled !== null && styled.closest('[data-testid="mcp-discovery"]') !== null;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('MCPDiscovery error reporting', () => {
  it('shows the missing-scope consent message instead of the empty state', async () => {
    const fetchMock = stubDiscover(
      reply(200, { items: [], error: CONSENT, error_code: 'missing_scope' }),
    );
    renderDiscovery();

    const message = await screen.findByText(CONSENT, exact);
    expect(hasPreLine(message)).toBe(true);
    expect(screen.queryByText(EMPTY_STATE)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('still shows the empty state when the list is empty and there is no error', async () => {
    stubDiscover(reply(200, { items: [] }));
    renderDiscovery();

    expect(await screen.findByText(EMPTY_STATE)).toBeInTheDocument();
  });

  it('shows the error from a non-OK response body', async () => {
    const backendError = 'Could not list MCP connections: RuntimeError';
    stubDiscover(reply(500, { items: [], error: backendError, error_code: 'discovery_failed' }));
    renderDiscovery();

    expect(await screen.findByText(backendError)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_STATE)).not.toBeInTheDocument();
  });

  it('shows the HTTP status when a non-OK response has no parseable body', async () => {
    stubDiscover(unparseableReply(502));
    renderDiscovery();

    expect(await screen.findByText('Could not list MCP connections (502).')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });
    expect(screen.queryByText(EMPTY_STATE)).not.toBeInTheDocument();
  });
});
