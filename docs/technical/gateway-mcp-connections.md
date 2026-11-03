# AI Gateway MCP connections

**One-Line Summary:** How an admin makes a Databricks AI Gateway MCP service (for example LakeDraw, a diagram app) available to the Architect or Data analyst agent, and how users then sign in to it and use it.

---

## 1. What this is

Databricks AI Gateway serves MCP services at `{host}/ai-gateway/mcp-services/<catalog>.<schema>.<service>`. Some are built in (`system.ai.web_search`, `system.ai.github`, ...); admins can add their own on top of a Unity Catalog HTTP connection.

Tellr **registers** a Gateway service rather than listing them. Listing services needs the `unity-catalog` scope, which Databricks Apps does not allow, so a user token cannot do it. Calling a service needs only the `ai-gateway` scope, so once an admin has typed the service name in, Tellr can call it as the signed-in user (never as the app's service principal).

Gateway connections work in **agent mode only**. Legacy decks ignore them, and the chip says "agent mode only". A deck with no Gateway connection behaves exactly as before.

## 2. Prerequisites

- The app's `user_api_scopes` must include `ai-gateway`. Check it:

  ```bash
  databricks apps get <app> -o json
  ```

  `tellr.update()` adds missing scopes only on a best-effort basis and has skipped them before, so verify rather than assume.
- Users whose consent predates the scope must re-consent. Tellr shows the consent message when a call is refused for a missing scope.

## 3. Step 1: create the connection and service in Databricks

Skip this if the service already exists (for example the built-in ones). Tellr does not create Unity Catalog objects. The steps below are what worked on tellr-dev; the `CREATE CONNECTION` SQL in the original LakeDraw document does **not** work as written. The same text is in the collapsed "How to create the service in Databricks" panel on the Connections tab.

**1. Create a schema-level HTTP connection.** `POST /api/2.1/unity-catalog/connections` with:

- `name`: a one-part name
- `parent`: `schemas/<catalog>.<schema>`
- `connection_type`: `HTTP`
- `options` (LakeDraw values):

| Option | Value |
|--------|-------|
| `host` | `https://lakedraw-stg-7474654280603666.aws.databricksapps.com` |
| `port` | `443` |
| `base_path` | `/mcp/` |
| `authorization_endpoint` | `https://fevm-lakedraw.cloud.databricks.com/oidc/v1/authorize` |
| `token_endpoint` | `https://fevm-lakedraw.cloud.databricks.com/oidc/v1/token` |
| `client_id` | `9eb36248-4a77-415e-87b0-191d19060d95` |
| `oauth_scope` | `all-apis offline_access` |
| `oauth_credential_exchange_method` | `header_and_body` |

**Do not pass** `credential_type` (Unity Catalog infers `OAUTH_U2M_MAPPING` and refuses it if given) or `is_mcp_connection` (refused on schema-level connections).

**2. Create the MCP service** with `ai_gateway.create_mcp_service`:

- parent: `schemas/<catalog>.<schema>`
- id: `<service>`
- config: `source_connection.name = connections/<catalog>.<schema>.<conn>` and `include_tool_selectors = ["*"]`

**3. Grant users access:**

```sql
GRANT USE CATALOG ON CATALOG <catalog> TO <users>;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO <users>;
GRANT EXECUTE ON MCP SERVICE <catalog>.<schema>.<service> TO <users>;
```

`ON MCP SERVICE` is required: `GRANT EXECUTE ON SERVICE …` is a parse error on DBSQL. The permissions API works too: `PATCH /api/2.1/unity-catalog/permissions/mcp_service/<catalog>.<schema>.<service>` with `{"changes": [{"principal": "<user>", "add": ["EXECUTE"]}]}`.

Unity Catalog's `EXECUTE` grant is the only access control. Tellr has no per-connection permissions of its own.

## 4. Step 2: register it in Tellr (Admin -> Connections)

On the Admin page, open the **Connections** tab and click **Add connection**.

| Field | Notes |
|-------|-------|
| Service name | `catalog.schema.service`. Cannot be changed after saving. |
| Display name | Shown on chips, in the picker, in progress rows and in chat messages. |
| Description | Optional, user-facing. |
| Agent | **Architect** or **Data analyst** (radio). See below. |
| Instructions | Optional, up to 4000 characters (counter shown). Model-facing guidance for using the tools. |

**Test connection** lists the service's tools **as you (the admin)**, as checkboxes, or says why it cannot (sign-in link, access denied, missing scope, not found, unavailable). Untick tools to build an **allowlist**; leaving all ticked means "All tools". Unticking every tool is not allowed (Save is disabled until at least one is ticked). You can **Save** without a passing test, since you may not be signed in or granted yet. Edit, enable/disable and Delete (with a confirm) are in the table.

**Which agent.** A connection is bound to exactly one agent:

- **Architect:** plans the deck. Gateway tools join its run (it makes tool calls before writing the deck plan). Use this for things like diagrams.
- **Data analyst:** Gateway tools join its existing toolset beside Genie One, for data fetches.

The instructions reach the model in each tool's description, as `<display name>: <instructions>` followed by the tool's own description. No agent prompts change. Keep instructions short, and use the allowlist to keep the tool list small.

## 5. Step 3: users add it to a deck

In the deck's agent config bar, open the **MCP Server** picker. Registered connections appear first, under an **AI Gateway** heading; the existing Unity Catalog connections follow under **Unity Catalog**. Each user adds the connection to their own deck config. Tellr rejects saving a connection that is not registered or has been disabled.

### Per-user sign-in

Services behind a per-user OAuth (U2M) connection, such as LakeDraw, GitHub or Slack, need each user to sign in once.

- **On the chip:** a **Sign in to {name}** link opens `{host}/mcp-service-login?name=<service>` in a new tab. After signing in, click **Check again**.
- **Mid-turn:** if a turn needs the service and the user is not signed in, the chat posts "To use {name}, sign in here: ..." with a clickable link, and the deck still builds without that connection. Ask again after signing in. That notice is the only chat message with a link: the server marks it, and only its https sign-in URL is clickable. Every other message, including any URL a model or a service writes, is plain text.

Other chip states: " · agent mode only" (legacy deck), " · no access", " · needs permission", " · not found", " · unavailable" (also shown if an admin removed or disabled the connection).

## 6. Images from tools

When a tool returns an image (an MCP image block, or a base64 field such as LakeDraw's `data_base64`), Tellr saves it as a Tellr image owned by the user and gives the model a `{{image:TOKEN}}` reference. The model puts that reference in the slide's content brief and the slide builder embeds it. Image data never goes into the model's context, and Tellr checks the references in code: a mistyped token is corrected when exactly one known token shares its first 12 characters, otherwise removed (and the user is told). Images over 5 MB are not saved.

Tellr has no diagram-specific code. Linking a diagram back to its editor ("Edit in LakeDraw: ...") is done by the connection's instructions (section 8), not by Tellr.

## 7. Limits

| Limit | Value |
|-------|-------|
| One tool call | 90 s (clipped to the remaining budget) |
| Listing tools | 30 s |
| Architect, per turn | 12 calls / 360 s, shared by every architect pass in the turn (including retries) |
| Data analyst, per run | 6 calls / 300 s when Gateway tools are present (3 / 300 s with Genie One only) |
| New Gateway call | none start once the turn is 700 s old (the job limit is 1200 s) |
| Tool result text | capped (at least 32,000 characters; truncation is stated) |

LakeDraw takes about 4-5 calls per diagram, so the architect budget allows about two diagrams per turn. Tool output is treated as data, not instructions.

## 8. Worked example: LakeDraw

LakeDraw builds an architecture diagram from a node/edge spec, saves it under the user's own LakeDraw account, and exports a PNG. Register it for the **Architect**.

| Workspace | Service name |
|-----------|--------------|
| Logfood | `main.gtm_ai_tooling.lakedraw` (already exists; skip step 1) |
| tellr-dev | `db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw` |

**Recommended instructions** (paste into the Instructions field):

```text
Use LakeDraw when the user asks for an architecture, data-flow or system diagram, or a slide clearly needs one. Steps: call lakedraw_list_node_types once (mode "architecture") to learn valid node types; call lakedraw_create_from_spec with phase "validate"; fix any issues and validate again; then call it with phase "persist", the validation_digest, a new client_create_id (a fresh UUID), and response_detail "compact"; then call lakedraw_export_diagram with format "png". Put the returned {{image:…}} reference in that slide's content_brief, and add "Edit in LakeDraw: <diagram_url>" to the brief so the slide links to it. Record "LakeDraw diagram_id: <id>" in the slide's hands_off so later turns can re-export it. At most 100 nodes and 100 edges. Do not use lakedraw_edit_diagram; to change a diagram, create a new one from an updated spec.
```

**Recommended allowlist:** `lakedraw_list_node_types`, `lakedraw_create_from_spec`, `lakedraw_export_diagram`, `lakedraw_get_diagram`.

The admin must sign in to LakeDraw (via the Test connection sign-in link) before Test connection can list its tools.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Sign in" link, or JSON-RPC `-32006` | The user has not signed in to a U2M service (an HTTP 401, or a 200 reply saying the request was rejected with HTTP 401) | Open the link, sign in, click **Check again** |
| Access denied / "no access" | No `EXECUTE` on the service | Grant `USE CATALOG`, `USE SCHEMA` and `EXECUTE` (section 3) |
| Missing scope / "needs permission" | The token lacks `ai-gateway` | Check `user_api_scopes` (section 2); the user re-consents |
| Not found | Wrong service name, or the service was deleted | Check the three-part name in Databricks |
| "unavailable" | Admin disabled or removed the connection, or the service timed out or failed | Re-enable or re-register it on the Connections tab; retry |
| "unavailable right now (the model could not use its tools)" | The model call that carried the connection's tools failed (for example, the model provider refused a tool's input schema, or the model never finished its tool calls). Tellr made the same call again without the Gateway tools, so the deck was still built | Check the app log for `gateway_tools_failed` (it names the exception type); narrow the allowlist to the tools the agent needs |
| Tools never appear in a turn | Connection bound to the other agent, or the allowlist excludes them | Check the Agent radio and the allowlist |
