# Usage attribution: every Tellr request is identifiable — design

Date: 2026-11-18. Status: approved.

Decisions marked **(decided)** were approved by the owner on 2026-11-19. Unmarked text
describes the code as it stands on `main` at c1b11d9f (v0.5.7).

## Intent

Every request Tellr makes should say that it came from Tellr, which version sent it and
which feature it was for, and the app's database should be linked to the app. Then what
Tellr uses shows up correctly in the workspace's own usage and billing tables, so an admin
can see what the app costs to run and which part of it the cost comes from. Databricks
uses the same labels to understand how Tellr is adopted.

Today some of these labels are wrong and some are missing, so part of what Tellr uses
cannot be told apart from other apps in the same workspace.

The rule for the branch is: **identifiers only**. A label is a product name, a version or
one of a fixed list of feature names. No prompt, no deck content, no user text and no
customer name is ever put in one. The branch adds no behaviour, no permission and no
network call, sends no data anywhere new, and does nothing that can fail an install or an
upgrade.

## What the code does today

Checked against the code on `main`, the pinned `databricks-sdk==0.157.0` installed in a
clean environment, and a test install on a dev workspace.

1. **The SDK clients report version `0.1.0` on every deployed app.**
   `_get_package_version()` (`src/core/databricks_client.py:54`) imports `src._version`,
   which is gitignored and is not generated when the app wheel is built, so it falls back
   to the `0.1.0` placeholder in `src/__init__.py`. A deployed 0.5.x app therefore sends
   `tellr-app-system/0.1.0`. `gateway_clients._tellr_version()` already reads the
   installed wheel's metadata and reports the real version; the SDK clients do not use it.
2. **Agent-mode Genie calls carry no Tellr label.** `GenieAgentClient._genie`
   (`src/services/agent_tools/genie_agent.py:150`) builds a bare `WorkspaceClient`, so its
   requests go out as `unknown/0.0.0 databricks-sdk-py/…`. Legacy mode uses the labelled
   per-user client (`tellr-app-<hash>`). So Genie usage is identifiable in Legacy mode and
   not in Agent mode.
3. **Genie One and every other MCP call carries no Tellr label.** `build_user_mcp_client`
   (`src/services/agent_tools/mcp_transport.py:99`) opens an `httpx.AsyncClient` with no
   headers, so the calls arrive as `python-httpx/<version>` and cannot be told apart from
   another app's.
4. **Request tags are not recorded on MCP routes.** The AI Gateway records the
   request-tags header on model routes only. For MCP routes the **User-Agent** is what is
   recorded.
5. **An autoscaling install's Lakebase is not linked to its app.** `_create_app`
   (`packages/databricks-tellr/databricks_tellr/deploy.py:1686`) attaches a database
   resource only for provisioned Lakebase and passes none for autoscaling, which is what a
   new install gets. The comment there says an autoscaling resource is not supported; the
   pinned SDK now has one (`AppResource.postgres`, `AppResourcePostgres(branch, database,
   permission)`). Without the resource, the database's usage is not attributed to the app.
6. **The SDK also offers a usage policy and custom tags** (`App.usage_policy_id`,
   `DatabaseInstance.custom_tags`, `ProjectSpec.custom_tags`). They need the admin to
   create and pass a policy, and the app resource in 5 does the job without one. Out of
   scope (see "Considered and not included").
7. **The per-user client is barely used on current versions.** It is labelled
   `tellr-app-<12-hex hash of the user's email local part>`. Genie and MCP calls go around
   it (2, 3), and the one call made while building it (`current_user.me()`,
   `databricks_client.py:478`) is made on the unlabelled first-stage client.
8. **LLM calls made as the app are already attributed.** The Gateway calls are tagged
   `source=tellr` (#373). The remaining `/serving-endpoints` calls (Legacy-mode agent,
   feedback chat, config validator, both judge backends) run as the app's service
   principal, and their usage is attributed to the app. They need no change.
9. **Nothing marks a deck as created through Tellr's MCP server.** `src/api/mcp_server.py`
   enqueues the same chat job as the browser, and neither the job nor the session records
   which one it was.

## Design

### 1. One version, everywhere (decided)

`_get_package_version()` returns the installed `databricks-tellr-app` wheel's version when
the wheel is installed, and falls back to today's chain (`src._version`, `src.__version__`,
`"unknown"`) otherwise. `gateway_clients._tellr_version()` becomes a call to it, so the two
cannot drift again. The function moves to a new leaf module, `src/core/attribution.py`,
with the product constants (`PRODUCT_NAME_SYSTEM`, `PRODUCT_NAME_USER_PREFIX`) and
`_hash_username`; `databricks_client.py` re-exports the names it has today, so no caller or
test import changes.

The product **names** do not change. `tellr-app-system` and `tellr-app-<hash>` are the
labels in use today, and anything that reads them must keep working across the upgrade. Only `product_version` changes, from `0.1.0` to the real version.

### 2. No anonymous client (decided)

Every `WorkspaceClient` Tellr builds carries a Tellr product and the real version.

| Site | Today | After |
|---|---|---|
| `genie_agent.py:150` (Agent-mode Genie) | bare | `product=tellr-app-<hash>` of the signed-in user |
| `mcp_transport.py:147` (Genie One, Gateway MCP, UC-connection MCP) | bare | same |
| `tools/mcp_tool.py:68`, `:135` (Legacy MCP tool) | bare | same |
| `databricks_client.py:469` (first-stage client that calls `/Me`) | bare | `product=tellr-app-system` |
| `model_endpoint_catalog.py:201` | built from the system client's `Config` | verify it inherits the product; set it if not |

One helper in `src/core/attribution.py` supplies the keyword arguments:
`user_product_kwargs(token)` returns `{"product": "tellr-app-<hash>", "product_version":
<version>}`. It looks the label up by the user's token, which `_create_user_client`
records when it first computes the hash; several of these clients are built in worker
threads where the request's context is not visible, and every one of them holds the token.
Without a recorded token it falls back to the request's user (`get_current_user()`), then
to `tellr-app-unknown`. Only a SHA-256 of the token is kept. No site makes an extra
network call to learn the user.

The MCP HTTP client (`_UserMCPClient._session_run`) sends
`User-Agent: tellr/<version> python-httpx/<httpx version>`: product first and the
library's own agent kept after it, as the Gateway clients do. It sends no request-tags
header, because that header is not recorded on MCP routes (item 4 above).

**Guard.** A source-scan test, like the one in `tests/unit/test_gateway_clients.py`, fails
when any file under `src/` constructs a `WorkspaceClient` without a `product=` argument or
a `config=` argument, and when `mcp_transport.py` opens an `httpx` client without a
`User-Agent`. The Gateway guard exists because another product's tag was once dropped
silently by an unrelated change; this is the same protection for the SDK and MCP clients.

### 3. Lakebase linked to the app (decided; live-tested 19 Nov 2026)

For an autoscaling install, the installer attaches the Lakebase branch to the app as an
`AppResourcePostgres` resource named `app_database`. This is what makes the platform
attribute the database's usage to the app. `tellr.update` adds it to an existing app that
lacks it, and `tellr.create` adds it to a new one.

**The resource is attached only after the service principal's role exists.** On create,
the order is: create the app with no database resource (as today), run
`_ensure_sp_autoscaling_role`, then attach. Passing the resource to `apps.create` is not an
option (see the second test below).

- The attach follows `_ensure_app_user_api_scopes` and
  `secret_key.attach_secret_resource`: read the app, keep every existing resource, append
  the missing one, carry every mutable field, omit `compute_size`. An app that already has
  a resource named `app_database` is left alone.
- It is warn-and-continue on both paths: a failure prints one line and the install or
  update goes on.
- Connection settings stay as they are. The app keeps reading `LAKEBASE_PG_HOST`,
  `LAKEBASE_PROJECT_ID` and `LAKEBASE_ENDPOINT_NAME` from `app.yaml`.
- The resource names the branch the install uses: `production` for a normal install, the
  fork's own branch for a devloop fork (`lakebase_result["branch_id"]`).

**What the live test showed.** A fresh `tellr.create` of v0.5.7 on a new autoscaling
project, on the dev workspace, then:

| Step | Result |
|---|---|
| Attach the resource to the running app | Accepted. No restart. Description and user scopes kept. The branch's roles unchanged: the same service-principal role, same `LAKEBASE_OAUTH_V1` login, nothing added. |
| Redeploy | Started first time. The platform injected `PGHOST` and `PGUSER`, equal to the endpoint host and the service principal the app already used. `_get_database_url` took the autoscaling path as before. All 48 tables present with the same owner, and a new row was written. |
| Attach again | No change. |
| `tellr.update` with the released 0.5.7 installer | Kept the resource. App healthy and writing afterwards. |
| Fresh install, the installer's own steps in today's order with the attach added after the role setup and before the first deploy | Role setup succeeded. Roles afterwards were only the ones the installer created. First deploy healthy: 48 tables owned by the service principal, and a row written. |
| The same app pinned to v0.4.2, then to v0.2.7 (the oldest release), each on a fresh schema with the resource attached | Both started healthy on the autoscaling path, created their own schema (28 and 18 tables) with the same owner, and logged in without error. |

**Why not at `apps.create`.** A second app was created with the resource already on it,
against a fresh branch. The platform then created the service principal's role itself, as
`dbrx-apps-<client id>` and with no membership role. `_ensure_sp_autoscaling_role` looks
for `sp-<client id>`, does not find it, tries to create it, and fails with "role with that
name already exists", which aborts the install. Attaching after the role exists avoids
this, and is the order the first test proved.

Not yet confirmed: that billing then attributes the project's usage to the app. To be
checked on the test install before release.

### 4. A `component` tag on Gateway calls (decided)

The request tag becomes `{"source": "tellr", "component": "<value>"}`. `source` is
unchanged, so every existing reader keeps working. `component` is one of a fixed set, and
a value outside the set is dropped, so a tag can never carry free text:

| Value | Client |
|---|---|
| `generation` | graph agents (`DatabricksModelAdapter._default_model_factory`) |
| `title` | session titles (`build_session_title_model`) |
| `export` | PPTX and Google Slides export |
| `image` | image generation |

`gateway_request_headers`, `gateway_chat_model` and `gateway_openai_client` take an
optional `component`. The existing tests pin the header to exactly
`{"source": "tellr"}`; they are updated to the new exact values, and one new test proves an
unknown component falls back to `{"source": "tellr"}`.

### 5. An `entrypoint` tag for decks made through Tellr's MCP server (decided)

`src/api/mcp_server.py` marks the turn `mcp` just before it enqueues the chat job, and the
browser route marks it `app`. The mark is a ContextVar; `enqueue_job` already copies the
context into the worker, so every model call of the turn sees it, and
`gateway_request_headers` adds `"entrypoint"` to the tag when it is one of those two
values. This separates what other agents use through Tellr from what its own users use.

On `main` an MCP job runs the Legacy engine, whose deck calls do not go through the
Gateway, so the `mcp` value shows on that job's title call today. It reaches the deck
calls when MCP jobs run on the graph, with no further change.

## Considered and not included

- **A per-user label on Gateway LLM calls.** Left out for privacy. It would put a
  per-person identifier on every LLM record, and the hash of an email local part can be
  guessed for a known name. The branch only keeps the per-user label the SDK clients
  already send. **(decided: left out.)**
- **A usage policy or custom tags** on the app or the Lakebase project (item 6 above).
- **Moving the `/serving-endpoints` paths onto the Gateway** (item 8 above). The default
  judge runs inside `mlflow.genai.evaluate`, which builds its own client.
- **Postgres `application_name`** and **logging the service principal's id at startup.**
  Neither adds anything the labels above do not.
- **Tags on MLflow experiments or traces.** Tracing writes through the customer's SQL
  warehouse and is not separable unless that warehouse is dedicated.

## Non-goals

- No dashboard, table, endpoint or setting in Tellr. `usage_events` and the admin usage
  page are unchanged.
- No change to which identity makes a call, to any scope, or to any request body.
- No change to the product names or to `source=tellr`.

## Error handling

Every addition is passive. `user_product_kwargs()` and the version lookup never raise: a
failure yields `tellr-app-unknown` and `"unknown"`. A tag value outside its allow-list is
omitted. The installer change prints a warning and continues.

## Testing

- **Unit.** Version: wheel metadata wins, the fallback chain is unchanged. Product
  arguments: bound user, no user, and that no network call is made. Wire tests on a mock
  transport: Agent-mode Genie and the first-stage `/Me` request carry the product and
  version; an MCP request carries exactly one `User-Agent`, starting `tellr/`, and no tag
  header. Gateway: exact tag for each component, unknown component dropped, entrypoint
  present only inside a job that set it, every tool-loop round still tagged. Installer:
  create passes the resource for autoscaling and not for provisioned; update appends
  without dropping resources, scopes or description, is a no-op the second time, and
  continues when the API refuses.
- **Guards.** The two source scans in section 2, each with a sabotage case.
- **Live, on the dev workspace (devloop, never devtest).** The section 3 sequence again
  with the new installer (create, update, second update), then one
  deck in Agent mode with a Genie Agent and Genie One, a title and a PPTX export. Done when
  the workspace's own system tables show: SDK requests with the deployed version;
  Genie requests as `tellr-app-<hash>`; Genie One requests as `tellr/<version>`; Gateway
  records with `component`; and the Lakebase branch declared as the app's resource.

## How it reaches installs

Sections 1, 2, 4 and 5 are in the app wheel and arrive with any upgrade. Section 3 is in
the installer and takes effect the next time `tellr.create` or `tellr.update` runs with
the new `databricks-tellr` package.
