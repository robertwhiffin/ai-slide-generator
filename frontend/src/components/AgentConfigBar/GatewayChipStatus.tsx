/**
 * Status suffix of a Gateway MCP chip: the per-user sign-in / access state of one connection.
 *
 * Legacy decks never call the Gateway (agent mode only), so no status is fetched for them.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../services/api';
import type { GatewayMcpStatus, GatewayMcpTool } from '../../types/agentConfig';

const SHORT_REASON: Record<string, string> = {
  access_denied: 'no access',
  missing_scope: 'needs permission',
  not_found: 'not found',
  unavailable: 'unavailable',
};

/** The server builds the sign-in URL on the workspace host; only an https link is ever rendered. */
const HTTPS_URL = /^https:\/\//i;

export const GatewayChipStatus: React.FC<{ tool: GatewayMcpTool; legacyDeck: boolean }> = ({
  tool,
  legacyDeck,
}) => {
  const [status, setStatus] = useState<GatewayMcpStatus | null>(null);
  const latest = useRef(0);

  const load = useCallback(() => {
    const ticket = ++latest.current;
    api
      .getGatewayMcpStatus(tool.service_name)
      .then((s) => {
        if (ticket === latest.current) setStatus(s);
      })
      .catch(() => {
        // Status is advisory; a failed lookup leaves the chip without a status suffix.
      });
  }, [tool.service_name]);

  useEffect(() => {
    if (legacyDeck) return;
    load();
    return () => {
      latest.current++;
    };
  }, [legacyDeck, load]);

  if (legacyDeck) {
    return <span className="text-gray-500 font-normal">{' · agent mode only'}</span>;
  }
  if (!status || status.state === 'ready') return null;

  if (status.state === 'sign_in_required') {
    const signInUrl =
      status.sign_in_url && HTTPS_URL.test(status.sign_in_url) ? status.sign_in_url : null;
    return (
      <>
        {signInUrl && (
          <a
            href={signInUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="underline font-normal"
            onClick={(e) => e.stopPropagation()}
          >
            {`Sign in to ${tool.display_name}`}
          </a>
        )}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            load();
          }}
          className="font-normal text-gray-600 hover:underline"
        >
          Check again
        </button>
      </>
    );
  }

  if (status.state === 'not_registered') {
    return <span className="text-gray-500 font-normal">{' · unavailable'}</span>;
  }

  return (
    <span className="text-gray-500 font-normal opacity-70" title={status.message ?? undefined}>
      {` · ${SHORT_REASON[status.state] ?? 'unavailable'}`}
    </span>
  );
};
