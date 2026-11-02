/**
 * Admin -> Connections: register, edit, enable/disable, delete and test AI Gateway MCP
 * connections (UC MCP services). Users pick the enabled ones in the deck tool picker.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';
import { useToast } from '../../contexts/ToastContext';
import type {
  GatewayConnection,
  GatewayConnectionAgent,
  GatewayConnectionUpdate,
  GatewayMcpStatus,
} from '../../types/agentConfig';

const INSTRUCTIONS_MAX = 4000;
/** Only an https sign-in link is ever rendered (same rule as the chip). */
const HTTPS_URL = /^https:\/\//i;

const AGENT_LABEL: Record<GatewayConnectionAgent, string> = {
  architect: 'Architect',
  data_analyst: 'Data analyst',
};

const CONNECTION_BODY = `POST /api/2.1/unity-catalog/connections
{
  "name": "<conn>",
  "parent": "schemas/<catalog>.<schema>",
  "connection_type": "HTTP",
  "options": {
    "host": "https://lakedraw-stg-7474654280603666.aws.databricksapps.com",
    "port": "443",
    "base_path": "/mcp/",
    "authorization_endpoint": "https://fevm-lakedraw.cloud.databricks.com/oidc/v1/authorize",
    "token_endpoint": "https://fevm-lakedraw.cloud.databricks.com/oidc/v1/token",
    "client_id": "9eb36248-4a77-415e-87b0-191d19060d95",
    "oauth_scope": "all-apis offline_access",
    "oauth_credential_exchange_method": "header_and_body"
  }
}`;

const SERVICE_BODY = `ai_gateway.create_mcp_service
  parent: schemas/<catalog>.<schema>
  id: <service>
  config:
    source_connection.name: connections/<catalog>.<schema>.<conn>
    include_tool_selectors: ["*"]`;

const GRANTS = `GRANT USE CATALOG ON CATALOG <catalog> TO <users>;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO <users>;
GRANT EXECUTE ON SERVICE <catalog>.<schema>.<service> TO <users>;`;

const HelpPanel: React.FC = () => {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-4 border border-gray-200 rounded bg-white">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="gateway-help-body"
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        How to create the service in Databricks
      </button>
      {open && (
        <div id="gateway-help-body" className="px-4 pb-4 text-sm text-gray-700 space-y-3">
          <p>
            1. Create a schema-level HTTP connection. Use a one-part name, and leave out
            credential_type and is_mcp_connection. Example values:
          </p>
          <pre className="bg-gray-50 p-2 rounded overflow-x-auto text-xs">{CONNECTION_BODY}</pre>
          <p>2. Create the MCP service on that connection:</p>
          <pre className="bg-gray-50 p-2 rounded overflow-x-auto text-xs">{SERVICE_BODY}</pre>
          <p>3. Grant users access:</p>
          <pre className="bg-gray-50 p-2 rounded overflow-x-auto text-xs">{GRANTS}</pre>
          <p>Then register the service here, using its three-part name.</p>
        </div>
      )}
    </div>
  );
};

interface FormState {
  editing: GatewayConnection | null;
  serviceName: string;
  displayName: string;
  description: string;
  agent: GatewayConnectionAgent;
  instructions: string;
  enabled: boolean;
}

const blankForm = (): FormState => ({
  editing: null,
  serviceName: '',
  displayName: '',
  description: '',
  agent: 'architect',
  instructions: '',
  enabled: true,
});

const formFor = (c: GatewayConnection): FormState => ({
  editing: c,
  serviceName: c.service_name,
  displayName: c.display_name,
  description: c.description ?? '',
  agent: c.agent,
  instructions: c.instructions ?? '',
  enabled: c.enabled,
});

/** Exactly the six editable fields: the PUT schema forbids extras. */
const bodyFor = (c: GatewayConnection, over: Partial<GatewayConnectionUpdate> = {}): GatewayConnectionUpdate => ({
  display_name: c.display_name,
  description: c.description,
  agent: c.agent,
  instructions: c.instructions,
  tool_allowlist: c.tool_allowlist,
  enabled: c.enabled,
  ...over,
});

export const AdminConnections: React.FC = () => {
  const { showToast } = useToast();
  const [connections, setConnections] = useState<GatewayConnection[] | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<GatewayMcpStatus | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setConnections(await api.listGatewayConnections());
    } catch (e) {
      setConnections([]);
      showToast(e instanceof Error ? e.message : 'Failed to load connections', 'error');
    }
  }, [showToast]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openForm = (next: FormState) => {
    setForm(next);
    setTestResult(null);
    setChecked(new Set());
    setSaveError(null);
  };

  const closeForm = () => {
    setForm(null);
    setTestResult(null);
    setSaveError(null);
  };

  const patch = (p: Partial<FormState>) => setForm((f) => (f ? { ...f, ...p } : f));

  const runTest = async () => {
    if (!form || !form.serviceName.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testGatewayConnection(form.serviceName.trim());
      setTestResult(result);
      if (result.state === 'ready') {
        const existing = form.editing?.tool_allowlist;
        const names = result.tools.map((t) => t.name);
        setChecked(new Set(existing ? names.filter((n) => existing.includes(n)) : names));
      }
    } catch (e) {
      setTestResult({
        state: 'unavailable',
        message: e instanceof Error ? e.message : 'Connection test failed',
        sign_in_url: null,
        tools: [],
      });
    } finally {
      setTesting(false);
    }
  };

  const toggleTool = (name: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const allowlistToSave = (): string[] | null => {
    if (testResult?.state === 'ready') {
      const names = testResult.tools.map((t) => t.name);
      const picked = names.filter((n) => checked.has(n));
      return picked.length === names.length ? null : picked;
    }
    // No (successful) test this session: keep whatever was stored.
    return form?.editing?.tool_allowlist ?? null;
  };

  const save = async () => {
    if (!form) return;
    setSaving(true);
    setSaveError(null);
    const fields: GatewayConnectionUpdate = {
      display_name: form.displayName.trim(),
      description: form.description.trim() || null,
      agent: form.agent,
      instructions: form.instructions.trim() || null,
      tool_allowlist: allowlistToSave(),
      enabled: form.enabled,
    };
    try {
      if (form.editing) {
        await api.updateGatewayConnection(form.editing.id, fields);
      } else {
        await api.createGatewayConnection({ service_name: form.serviceName.trim(), ...fields });
      }
      closeForm();
      await load();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Failed to save connection');
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (c: GatewayConnection) => {
    try {
      const updated = await api.updateGatewayConnection(c.id, bodyFor(c, { enabled: !c.enabled }));
      setConnections((list) => (list ?? []).map((x) => (x.id === c.id ? updated : x)));
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to update connection', 'error');
    }
  };

  const remove = async (c: GatewayConnection) => {
    if (!window.confirm(`Delete the connection "${c.display_name}"? Decks that use it will lose it.`)) {
      return;
    }
    try {
      await api.deleteGatewayConnection(c.id);
      setConnections((list) => (list ?? []).filter((x) => x.id !== c.id));
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to delete connection', 'error');
    }
  };

  const signInUrl =
    testResult?.sign_in_url && HTTPS_URL.test(testResult.sign_in_url) ? testResult.sign_in_url : null;
  const inputCls = 'w-full border border-gray-300 rounded px-2 py-1 text-sm disabled:bg-gray-100';

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">AI Gateway connections</h2>
          <p className="text-sm text-gray-500">
            MCP services that users can add to the Architect or Data analyst agent.
          </p>
        </div>
        {!form && (
          <button
            type="button"
            onClick={() => openForm(blankForm())}
            className="px-3 py-1.5 text-sm rounded bg-blue-600 text-white hover:bg-blue-700"
          >
            Add connection
          </button>
        )}
      </div>

      <HelpPanel />

      {form && (
        <div className="mb-6 border border-gray-200 rounded bg-white p-4 space-y-3">
          <div>
            <label htmlFor="gw-service" className="block text-sm font-medium text-gray-700">
              Service name
            </label>
            <input
              id="gw-service"
              className={inputCls}
              value={form.serviceName}
              disabled={!!form.editing}
              placeholder="catalog.schema.service"
              onChange={(e) => {
                patch({ serviceName: e.target.value });
                // A result (and its tool picks) belongs to the service it was run against.
                setTestResult(null);
              }}
            />
          </div>
          <div>
            <label htmlFor="gw-display" className="block text-sm font-medium text-gray-700">
              Display name
            </label>
            <input
              id="gw-display"
              className={inputCls}
              value={form.displayName}
              onChange={(e) => patch({ displayName: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="gw-description" className="block text-sm font-medium text-gray-700">
              Description
            </label>
            <input
              id="gw-description"
              className={inputCls}
              value={form.description}
              onChange={(e) => patch({ description: e.target.value })}
            />
          </div>
          <fieldset>
            <legend className="text-sm font-medium text-gray-700">Agent</legend>
            <div className="flex gap-4">
              {(Object.keys(AGENT_LABEL) as GatewayConnectionAgent[]).map((a) => (
                <label key={a} className="flex items-center gap-1 text-sm">
                  <input
                    type="radio"
                    name="gw-agent"
                    checked={form.agent === a}
                    onChange={() => patch({ agent: a })}
                  />
                  {AGENT_LABEL[a]}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="gw-instructions" className="block text-sm font-medium text-gray-700">
              Instructions
            </label>
            <textarea
              id="gw-instructions"
              className={inputCls}
              rows={4}
              maxLength={INSTRUCTIONS_MAX}
              value={form.instructions}
              onChange={(e) => patch({ instructions: e.target.value })}
            />
            <div className="text-xs text-gray-500 text-right">
              {`${form.instructions.length} / ${INSTRUCTIONS_MAX}`}
            </div>
          </div>

          <div>
            <button
              type="button"
              onClick={() => void runTest()}
              disabled={testing || !form.serviceName.trim()}
              className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
            >
              Test connection
            </button>
            {testing && <span className="ml-2 text-sm text-gray-500">Testing...</span>}
            {testResult && testResult.state === 'ready' && (
              <ul className="mt-2 space-y-1">
                {testResult.tools.map((t) => (
                  <li key={t.name} className="text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={checked.has(t.name)}
                        onChange={() => toggleTool(t.name)}
                      />
                      {t.name}
                    </label>
                    {t.description && <span className="ml-6 text-xs text-gray-500">{t.description}</span>}
                  </li>
                ))}
              </ul>
            )}
            {testResult && testResult.state !== 'ready' && (
              <div className="mt-2 text-sm text-gray-700">
                {testResult.state === 'sign_in_required' && signInUrl && (
                  <a
                    href={signInUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline mr-2"
                  >
                    Sign in to continue
                  </a>
                )}
                <span>{testResult.message ?? testResult.state}</span>
              </div>
            )}
          </div>

          {saveError && (
            <div role="alert" className="text-sm text-red-600">
              {saveError}
            </div>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="px-3 py-1.5 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={closeForm}
              className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {connections === null ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : connections.length === 0 ? (
        <p className="text-sm text-gray-500">No connections registered yet.</p>
      ) : (
        <table className="w-full text-sm bg-white border border-gray-200 rounded">
          <thead>
            <tr className="text-left text-gray-600 border-b border-gray-200">
              <th className="p-2">Display name</th>
              <th className="p-2">Service name</th>
              <th className="p-2">Agent</th>
              <th className="p-2">Tools</th>
              <th className="p-2">Enabled</th>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {connections.map((c) => (
              <tr key={c.id} className="border-b border-gray-100">
                <td className="p-2">{c.display_name}</td>
                <td className="p-2 font-mono text-xs">{c.service_name}</td>
                <td className="p-2">{AGENT_LABEL[c.agent]}</td>
                <td className="p-2">
                  {c.tool_allowlist === null ? 'All tools' : `${c.tool_allowlist.length} tools`}
                </td>
                <td className="p-2">
                  <input
                    type="checkbox"
                    aria-label={`Enabled: ${c.display_name}`}
                    checked={c.enabled}
                    onChange={() => void toggleEnabled(c)}
                  />
                </td>
                <td className="p-2 text-right space-x-2">
                  <button
                    type="button"
                    aria-label={`Edit ${c.display_name}`}
                    onClick={() => openForm(formFor(c))}
                    className="text-blue-600 hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${c.display_name}`}
                    onClick={() => void remove(c)}
                    className="text-red-600 hover:underline"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};
