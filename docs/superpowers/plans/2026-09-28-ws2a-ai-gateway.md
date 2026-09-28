# Workstream 2a — Unity AI Gateway (`system.ai.*`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, also load `executing-plans-tellr` (see `CLAUDE.md`).

**Goal:** Send every graph model call, both export converters and session-title generation
through Unity AI Gateway. The Agent Definition Workbench must offer only the `system.ai.*`
models that the Gateway lists.

**Architecture:**
- Bump `databricks-langchain` to 0.20.0 and add `databricks-openai` 0.17.1.
- Graph calls: the default model factory constructs
  `ChatDatabricks(model=..., use_ai_gateway=True)`, so the existing structured-output
  binding seam is unchanged.
- Export: the converters use `DatabricksOpenAI(use_ai_gateway=True)`.
- Discovery and remote draft validation read `/api/ai-gateway/v2/endpoints`.
- A new save-only validator requires a `system.ai.*` name whenever a save changes a role's
  model.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, databricks-sdk, databricks-langchain,
databricks-openai, openai, httpx, pytest; React + TypeScript + Vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-09-28-ws2a-ai-gateway-system-ai-design.md`. Read it in
full before starting. It holds the platform facts in §2 and the decisions this plan
implements.

## Global Constraints

- **Branch:** `feat/ws2a-ai-gateway`. Never push without the user's confirmation. Push as
  the personal `robertwhiffin` account, never the EMU account.
- **Shared environment:** the Python environment is a shared pyenv. **Never run
  `pip install`, `npm install` or `uv`, and never create a `.venv`.** The one exception is
  the human step in Task 0.
- **Build file:** the Apps BUILD phase resolves only
  `packages/databricks-tellr-app/pyproject.toml`.
- **Exact pins in the app file:** `databricks-langchain==0.20.0` and
  `databricks-openai==0.17.1`.
- **Root `pyproject.toml`** keeps its ranged style: `databricks-langchain>=0.19.0` and
  `databricks-openai>=0.14.0`.
- **`requirements.txt`** uses exact pins that match the app file.
- **Gateway chat base URL:** `{host}/ai-gateway/mlflow/v1`. Never `/serving-endpoints` for
  in-scope call sites, and never an automatic fallback to it.
- **Gateway endpoint list:** `GET /api/ai-gateway/v2/endpoints`. Per name:
  `GET /api/ai-gateway/v2/endpoints/{name}`. The chat API-type marker is
  `mlflow/v1/chat/completions`.
- **Naming rule:** Gateway endpoint `databricks-<model>` ↔ invocable name
  `system.ai.<model>`.
- **Name regex for a changed model:** `^system\.ai\.[a-z0-9][a-z0-9._-]*[a-z0-9]$`.
- **New codes:**
  - `endpoint_not_gateway_model`, message: "Model name must start with `system.ai.` and
    contain only lowercase letters, digits, hyphens, underscores and periods."
  - `endpoint_not_chat_model`, message: "Endpoint is not a chat model."
- **Constants:**
  - export `DEFAULT_MODEL = "system.ai.claude-sonnet-4-5"`;
  - `SESSION_TITLE_MODEL = "system.ai.claude-opus-4-6"` in `src/core/defaults.py`;
  - `DEFAULT_CONFIG["llm"]` is **unchanged**.
- **Out of scope; do not touch their model calls:** the monolith (`agent.py`,
  `agent_factory.py`), MCP, the judge (`llm_judge.py`), feedback (`feedback_service.py`) and
  `config_validator.py`.
- **Pinned seams must pass unedited:**
  - exactly one `with_structured_output` binding, with no `include_raw`;
  - the production adapter passes no `transport_options`;
  - `run()` keeps four positional arguments.
- **The only allowed seam-test edits** are the `endpoint` → `model` key rename (Task 1) and
  the `use_ai_gateway` key addition. List each one in the corrections file.
- **Typed errors** never echo provider text or endpoint names.
- **Deploys** go to a **new** devloop instance, `--env devloop --instance ws2a`. Never
  `devtest`. Never redeploy `epic258` or `epic258-admin`.
- **PostgreSQL integration tests:** run with
  `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one file at a
  time. A skip counts as a failure. Never touch the `ai_slide_generator` database.
- **Baselines** are compared by failure cause. Known causes: the
  `test_deploy_autoscaling` `TestGetOrCreateLakebase` pair (#276), and the
  `test_usage_service` flake near 00:00 UTC (#278).

## Review Focus

These are the five input classes the spec implies but that no happy-path test covers,
most likely to bite first:

1. **Rollback to a pre-2a release.** Every role names `databricks-*`, and rollback must
   still succeed. It re-validates through `_save_local_validators`. → Task 4, Step 1, test
   `test_rollback_to_a_legacy_release_is_not_blocked_by_the_gateway_name_rule`.
2. **A prompt-only edit on a role still named `databricks-*`** must save, including its
   remote check. → Task 4, `test_unchanged_legacy_model_saves`; Task 3,
   `test_remote_check_looks_up_a_legacy_name_as_is`.
3. **Publishing a draft where only untouched roles still name `databricks-*`** must
   succeed. → Task 4, `test_publication_with_untouched_legacy_roles_is_not_blocked`.
4. **An embedding model picked from the list** (it appears in discovery) is refused at save
   with `endpoint_not_chat_model` and no leaked text. → Task 3,
   `test_remote_check_refuses_an_embedding_endpoint`.
5. **A saved draft whose role names a legacy model** shows that model visibly in the
   picker, where no radio option is checked, and does not silently drop it. → Task 7,
   `shows the current model when it is not in the discovered list`.

---

## File map

| File | Change | Task |
|---|---|---|
| `packages/databricks-tellr-app/pyproject.toml`, `pyproject.toml`, `requirements.txt` | Dependency pins | 0 |
| `tests/fixtures/mock_chat_completions.py` | Mock Gateway transport for real `ChatDatabricks` | 1 |
| `tests/unit/test_model_endpoint_probe.py` | Migrate `MockTransportWorkspace`, update kwargs assertion | 1 |
| `src/services/agent_runtime.py` | Default factory adds `use_ai_gateway=True`; binding passes `model=` | 1 |
| `tests/unit/test_agent_runtime.py` | Rename seam keys, new Gateway-path test | 1 |
| `src/services/model_endpoint_catalog.py` | Gateway discovery, Gateway remote check, new codes, name mapping | 2, 3 |
| `tests/unit/test_model_endpoint_catalog.py` | Rewrite discovery and remote tests for the Gateway API | 2, 3 |
| `src/services/graph_configuration_draft.py` | `_gateway_model_name_validator` in the two saves | 4 |
| `tests/unit/test_graph_configuration_draft.py` (+ route and integration tests that save a changed model) | New rule tests; changed-model fixtures move to `system.ai.*` | 3, 4 |
| `src/services/gateway_openai.py` (new) | One constructor for the export OpenAI client | 5 |
| `src/services/html_to_pptx.py`, `src/services/html_to_google_slides.py` | Gateway client and `system.ai` constant | 5 |
| `tests/unit/test_html_to_pptx.py`, `tests/unit/test_google_slides_converter.py` | Client and parser tests | 5 |
| `src/core/defaults.py`, `src/api/services/session_naming.py`, `src/api/services/chat_service.py` | `SESSION_TITLE_MODEL`, `build_session_title_model()`, both title sites | 6 |
| `tests/unit/test_session_naming.py` | Title model construction tests | 6 |
| `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx` (+ its test) | Remove the custom field; show the current model | 7 |
| PRD, handover, `docs/technical/backend-overview.md` | Docs | 8 |
| — | Live acceptance on devloop | 9 |

Corrections file: `docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md`. It is
created in Task 0 and appended to by every task.

---

### Task 0: Merge `main`, bump dependencies, prove the build and the naming rule

**Files:**
- Modify: `packages/databricks-tellr-app/pyproject.toml:17-26`, `pyproject.toml:29`,
  `requirements.txt:20-34`
- Create: `docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md`
- Create (not committed): `/tmp/ws2a_naming_probe.py`

**Interfaces:**
- Produces: a shared environment with `databricks-langchain==0.20.0` and
  `databricks-openai==0.17.1` installed. Every later task's tests depend on it.

> **Deviation from spec §4, recorded:** spec §4 step 5 (prove OBO titles through the
> Gateway) cannot run in Task 0, because titles only reach the Gateway after Task 6. It
> moves to Task 9 Step 2, with the same stop condition. Write this as the first entry of
> the corrections file.

- [ ] **Step 1: Corrections pre-pass.** Create the corrections file with the heading
  `# ws2a — plan-vs-code corrections`. Re-check each `file:line` locator in this plan
  against the current code, and record every mismatch. Re-probe any external-state fact
  before relying on it; do not trust the plan.

- [ ] **Step 2: Merge `main`.**

```bash
git fetch origin main && git merge origin/main
```

  Resolve conflicts by keeping `main`'s security and deploy changes and this branch's
  graph work. If a conflict touches `src/services/agent_runtime.py`,
  `model_endpoint_catalog.py` or `graph_configuration_*.py`, stop and report to the
  controller. Commit the merge.

- [ ] **Step 3: Record the baseline** before the bump:

```bash
pytest tests/unit -q -p no:cacheprovider 2>&1 | tail -40 > /tmp/ws2a-baseline-pre.txt
```

  In the corrections file, record the failures **by cause**, not by count.

- [ ] **Step 4: Edit the pins.**
  - In `packages/databricks-tellr-app/pyproject.toml`:
    - replace `"databricks-langchain==0.9.0",` with `"databricks-langchain==0.20.0",`;
    - add `"databricks-openai==0.17.1",` directly below it;
    - rewrite the comment `# databricks-langchain==0.9.0 requires openai>=1.99.9 directly.`
      as `# databricks-langchain==0.20.0 / databricks-openai==0.17.1 require openai>=1.99.9.`
  - In `requirements.txt`, apply the same two pins and the same comment edit.
  - In root `pyproject.toml`, change `"databricks-langchain>=0.1.0",` to
    `"databricks-langchain>=0.19.0",` and add `"databricks-openai>=0.14.0",` below it.

  Commit:

```bash
git add packages/databricks-tellr-app/pyproject.toml pyproject.toml requirements.txt
git commit -m "build: pin databricks-langchain 0.20.0 and add databricks-openai 0.17.1 for AI Gateway routing"
```

- [ ] **Step 5: HUMAN STEP — upgrade the shared environment.** The agent must not do this.
  Ask the user to run it and wait for confirmation:

```
! pip install "databricks-langchain==0.20.0" "databricks-openai==0.17.1"
```

  Then verify:

```bash
python -c "import databricks_langchain, databricks_openai, importlib.metadata as m; print(m.version('databricks-langchain'), m.version('databricks-openai'))"
python -c "from databricks_openai.utils import clients; print(clients._get_authorized_http_client, clients._resolve_base_url)"
```

  Expected: `0.20.0 0.17.1`, and two function reprs. If
  `databricks_openai.utils.clients._get_authorized_http_client` does not exist, record the
  real location in the corrections file. Task 1's fixture patches it.

- [ ] **Step 6: Post-bump baseline.** Run the same command into
  `/tmp/ws2a-baseline-post.txt`. The new failures are expected to be exactly the tests that
  drive the real `ChatDatabricks` through `serving_endpoints.get_open_ai_client` mocks,
  which 0.20 no longer calls:
  - `tests/unit/test_agent_runtime.py` (real-provider token-usage tests);
  - `tests/unit/test_model_endpoint_probe.py` (`real_provider` tests);
  - `tests/unit/test_agent_test_workbench.py` (`_real_provider_executor` tests).

  Record every new failure with its cause. **Any failure with a different cause must be
  stopped and reported.** It means the bump changed behaviour somewhere else, for example
  Genie or vector search.

- [ ] **Step 7: Prove the Apps build.** Use the `deploy-tellr-dev` skill. First confirm the
  push with the user.
  1. `git push origin feat/ws2a-ai-gateway`
  2. `gh workflow run publish-dev.yml --ref feat/ws2a-ai-gateway`, and note the `.devN`.
  3. `./scripts/deploy_local.sh create --env devloop --instance ws2a --profile tellr-dev --from-pypi <version>`

  Expected: the BUILD resolves and the app starts and passes migration. If the resolver
  does not finish, **stop**. Report to the user with the build log. The fallback is in spec
  §4.

- [ ] **Step 8: Prove the naming rule.** Write `/tmp/ws2a_naming_probe.py`, and do not
  commit it:

```python
"""One-off: prove databricks-<m> -> system.ai.<m> across the Gateway list (spec §4 step 4)."""
import httpx, openai
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

w = WorkspaceClient(profile="tellr-dev")


class _Auth(httpx.Auth):
    def auth_flow(self, request):
        request.headers["Authorization"] = w.config.authenticate()["Authorization"]
        yield request


gw = openai.OpenAI(base_url=w.config.host.rstrip("/") + "/ai-gateway/mlflow/v1",
                   api_key="no-token", http_client=httpx.Client(auth=_Auth()), max_retries=0)
listed = w.api_client.do("GET", "/api/ai-gateway/v2/endpoints")["endpoints"]
for entry in listed:
    name = entry["name"]
    detail = w.api_client.do("GET", f"/api/ai-gateway/v2/endpoints/{name}")
    types = detail.get("supported_api_types") or []
    if "mlflow/v1/chat/completions" not in types:
        print(f"SKIP non-chat {name} {types}")
        continue
    if not name.startswith("databricks-"):
        print(f"NOPREFIX {name}")
        continue
    model = "system.ai." + name.removeprefix("databricks-")
    try:
        gw.chat.completions.create(model=model, messages=[{"role": "user", "content": "hi"}], max_tokens=1)
        print(f"OK {model}")
    except openai.NotFoundError as error:
        body = str(error)
        print(f"{'REGION' if 'region' in body.lower() else 'FAIL'} {model}")
    except openai.APIError as error:
        print(f"ERROR {model} {type(error).__name__}")
for name in ("databricks-claude-opus-4-6", "databricks-gpt-oss-120b"):
    try:
        gw.chat.completions.create(model="system.ai." + name, messages=[{"role": "user", "content": "hi"}], max_tokens=1)
        print(f"UNEXPECTED-OK system.ai.{name}")
    except openai.NotFoundError:
        print(f"NEG-OK system.ai.{name}")
```

  Run `python /tmp/ws2a_naming_probe.py`. Paste the full output into the corrections file.
  **If any `FAIL` or `UNEXPECTED-OK` line appears, stop and report.** The naming rule does
  not hold.

- [ ] **Step 9: Commit the corrections file.**

```bash
git add docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md
git commit -m "docs(plan): ws2a Task 0 corrections, baseline and naming-rule proof"
```

---

### Task 1: Graph runtime through the Gateway (mock transport + model factory)

**Files:**
- Modify: `tests/fixtures/mock_chat_completions.py`
- Modify: `tests/unit/test_model_endpoint_probe.py:561-660` (`MockTransportWorkspace`, `_assert_only_the_mock_was_reached`)
- Modify: `src/services/agent_runtime.py:206-245` (`bind_structured_output_model`), `:321-325` (`_default_model_factory`)
- Modify: `tests/unit/test_agent_runtime.py:410-418`, `:673-681`, `:733` (key rename only)
- Test: `tests/unit/test_agent_runtime.py` (new test), `tests/unit/test_agent_test_workbench.py` (existing real-provider tests)

**Interfaces:**
- Consumes: the Task 0 environment.
- Produces:
  - `tests.fixtures.mock_chat_completions.install_mock_gateway_transport(monkeypatch)`;
  - `MockChatCompletionsWorkspace.config` (with `.host` and `.authenticate()`) and its
    `.requests: list[httpx.Request]`;
  - the model factory receives `model=` (not `endpoint=`), and the default factory adds
    `use_ai_gateway=True`.

- [ ] **Step 1: Write the failing Gateway-path test** in `tests/unit/test_agent_runtime.py`,
  next to `test_an_observed_real_provider_run_records_the_reported_token_usage`:

```python
def test_production_adapter_sends_the_stored_name_to_the_gateway_chat_route(monkeypatch):
    """Spec §6.1: the real ChatDatabricks posts to {host}/ai-gateway/mlflow/v1, stored name unchanged."""
    from tests.fixtures.mock_chat_completions import (
        MOCK_CHAT_HOST,
        MockChatCompletionsWorkspace,
        install_mock_gateway_transport,
    )

    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace(fake_output("architect"), usage=None)
    adapter = DatabricksModelAdapter(client_factory=lambda: workspace)

    adapter.invoke(
        agent_key="architect",
        configuration=AgentModelConfiguration(
            endpoint_name="databricks-claude-opus-4-6",
            temperature=0.7,
            max_tokens=60000,
            top_p=0.95,
        ),
        schema=OUTPUT_SCHEMAS["architect"],
        prompt="assembled prompt",
    )

    assert len(workspace.requests) == 1
    request = workspace.requests[0]
    assert request.url.host == MOCK_CHAT_HOST
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert json.loads(request.content)["model"] == "databricks-claude-opus-4-6"
```

  Add `import json` at the top of the test module if it is absent.

- [ ] **Step 2: Run it and verify it fails.**

  Run: `pytest tests/unit/test_agent_runtime.py::test_production_adapter_sends_the_stored_name_to_the_gateway_chat_route -v`

  Expected: FAIL, with `ImportError: cannot import name 'install_mock_gateway_transport'`.

- [ ] **Step 3: Rewrite the fixture.** In `tests/fixtures/mock_chat_completions.py`, keep
  `_handle` and the constants, and replace `get_open_ai_client` and the constructor with:

```python
from types import SimpleNamespace


class MockChatCompletionsWorkspace:
    """Expose only what ``DatabricksOpenAI`` reads: ``config.host`` and ``config.authenticate``.

    ``install_mock_gateway_transport`` routes the client's HTTP through ``_handle``,
    so no request can reach a network and no ambient credential is read.
    """

    def __init__(self, arguments: dict[str, Any], *, usage: dict[str, int] | None) -> None:
        self.arguments = arguments
        self.usage = usage
        self.requests: list[httpx.Request] = []
        self.config = SimpleNamespace(
            host=f"https://{MOCK_CHAT_HOST}",
            authenticate=lambda: {"Authorization": "Bearer unit-test-dummy-key"},
        )

    # _handle unchanged


def install_mock_gateway_transport(monkeypatch) -> None:
    """Make ``DatabricksOpenAI`` send through the workspace stand-in's ``_handle``.

    Only the transport is replaced: the real ``BearerAuth`` still reads
    ``workspace_client.config.authenticate``, and the real base-URL resolution still
    decides the path.
    """
    from databricks_openai.utils import clients

    def _mock_http_client(workspace_client, follow_redirects: bool = True) -> httpx.Client:
        return httpx.Client(
            auth=clients.BearerAuth(workspace_client.config.authenticate),
            transport=httpx.MockTransport(workspace_client._handle),
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(clients, "_get_authorized_http_client", _mock_http_client)
```

  Add `"install_mock_gateway_transport"` to `__all__`. Update every existing caller of
  `MockChatCompletionsWorkspace` in `tests/unit/test_agent_runtime.py` (`_real_chat_adapter`)
  and `tests/unit/test_agent_test_workbench.py` (`_real_provider_executor`). Each must call
  `install_mock_gateway_transport(monkeypatch)`; thread `monkeypatch` through the helper's
  signature and its callers. **Do not change any assertion in those tests.**

- [ ] **Step 4: Change the factory and the binding.** In `src/services/agent_runtime.py`:

```python
    @staticmethod
    def _default_model_factory(**kwargs: Any) -> Any:
        from databricks_langchain import ChatDatabricks  # type: ignore[import-untyped]

        # Workstream 2a: every graph model call goes through Unity AI Gateway
        # ({host}/ai-gateway/mlflow/v1).  There is no /serving-endpoints fallback.
        return ChatDatabricks(use_ai_gateway=True, **kwargs)
```

  In `bind_structured_output_model`, change `endpoint=configuration.endpoint_name,` to
  `model=configuration.endpoint_name,`. Nothing else in the function changes.

- [ ] **Step 5: Rename the seam keys.** In `tests/unit/test_agent_runtime.py`:
  - at `:412` and `:675`, `"endpoint": ...` becomes `"model": ...`;
  - at `:733`, `kwargs["endpoint"]` becomes `kwargs["model"]`;
  - update the docstring at `:707` ("as `endpoint`") to say `model`.

  Grep `tests/` for other `["endpoint"]` or `"endpoint":` assertions on model-factory kwargs
  (for example `tests/unit/test_model_endpoint_probe.py:155`) and rename those too. List
  every edited line in the corrections file.

- [ ] **Step 6: Migrate the probe harness.** In `tests/unit/test_model_endpoint_probe.py`:
  - Give `MockTransportWorkspace` a
    `self.config = SimpleNamespace(host=f"https://{MOCK_HOST}", authenticate=lambda: {"Authorization": "Bearer unit-test-dummy-key"})`.
  - Delete its `get_open_ai_client`.
  - Record client kwargs by wrapping the langchain helper. Add this helper and call it in
    each real-provider test:

```python
def _install_real_provider(monkeypatch, workspace: MockTransportWorkspace) -> None:
    from databricks_langchain import chat_models
    from tests.fixtures.mock_chat_completions import install_mock_gateway_transport

    install_mock_gateway_transport(monkeypatch)
    original = chat_models.get_openai_client

    def _recording(workspace_client=None, **kwargs):
        workspace.client_kwargs.append(kwargs)
        return original(workspace_client=workspace_client, **kwargs)

    monkeypatch.setattr(chat_models, "get_openai_client", _recording)
```

  In `_assert_only_the_mock_was_reached`, the kwargs assertion becomes:

```python
    assert workspace.client_kwargs == [
        {"timeout": PROBE_TIMEOUT_SECONDS, "max_retries": PROBE_MAX_RETRIES, "use_ai_gateway": True}
    ]
```

  Also add:

```python
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
```

  If `chat_models` imports `get_openai_client` under a different name in 0.20.0, patch the
  name it actually uses, and record it in the corrections file.

- [ ] **Step 7: Run the affected tests.**

```bash
pytest tests/unit/test_agent_runtime.py tests/unit/test_model_endpoint_probe.py tests/unit/test_agent_test_workbench.py -q
```

  Expected: all pass, and the Task 0 Step 6 failures are gone.
  `REAL_PROVIDER_CASES` classifications must be unchanged. If one changes, stop and
  report. It means `DatabricksOpenAI` wraps errors differently.

- [ ] **Step 8: Sabotage-verify.**
  1. Temporarily revert `use_ai_gateway=True` in the factory. The new test and the probe
     kwargs assertion must fail.
  2. Temporarily change `model=` back to `endpoint=`. The rename-seam tests must fail.
  3. Restore both.

- [ ] **Step 9: Commit.**

```bash
git add src/services/agent_runtime.py tests/fixtures/mock_chat_completions.py tests/unit/test_agent_runtime.py tests/unit/test_model_endpoint_probe.py tests/unit/test_agent_test_workbench.py docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md
git commit -m "feat(runtime): route graph model calls through Unity AI Gateway"
```

---

### Task 2: Workbench discovery from the Gateway endpoint list

**Files:**
- Modify: `src/services/model_endpoint_catalog.py:163-211` (`list_system_models`); add `gateway_invocable_name`
- Test: `tests/unit/test_model_endpoint_catalog.py`. Replace the `serving_endpoints.list()`
  discovery tests at `:74-160` and `:278-292`.

**Interfaces:**
- Produces:
  - `gateway_invocable_name(gateway_endpoint_name: str) -> str | None`, which returns
    `"system.ai.<m>"` for `"databricks-<m>"`, else `None`;
  - `gateway_endpoint_name(model_name: str) -> str`, which returns `"databricks-<m>"` for
    `"system.ai.<m>"` and any other name as it is (used by Task 3);
  - `SystemModelEndpoint.name` now holds the `system.ai.*` name, with `display_name`,
    `description` and `docs` all `None`.

- [ ] **Step 1: Write the failing tests.** Add a recording API client and replace the
  discovery tests:

```python
class RecordingApiClient:
    def __init__(self, *, responses=None, errors=None):
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.calls: list[tuple[str, str]] = []

    def do(self, method, path, **kwargs):
        assert not kwargs, f"unexpected request options: {kwargs}"
        self.calls.append((method, path))
        if path in self.errors:
            raise self.errors[path]
        return self.responses[path]


def gateway_catalog(api_client):
    return DatabricksModelEndpointCatalog(SimpleNamespace(api_client=api_client))


LIST_PATH = "/api/ai-gateway/v2/endpoints"


def test_list_system_models_maps_gateway_endpoints_to_system_ai_names_sorted():
    api = RecordingApiClient(responses={LIST_PATH: {"endpoints": [
        {"name": "databricks-gpt-oss-120b"},
        {"name": "databricks-claude-opus-5-5"},
        {"name": "databricks-bge-large-en"},
    ]}})

    discovery = gateway_catalog(api).list_system_models()

    assert api.calls == [("GET", LIST_PATH)]
    assert [item.name for item in discovery.endpoints] == [
        "system.ai.bge-large-en",
        "system.ai.claude-opus-5-5",
        "system.ai.gpt-oss-120b",
    ]
    assert all(
        (item.display_name, item.description, item.docs) == (None, None, None)
        for item in discovery.endpoints
    )


def test_list_system_models_drops_names_without_the_databricks_prefix():
    api = RecordingApiClient(responses={LIST_PATH: {"endpoints": [
        {"name": "my-provisioned-endpoint"},
        {"name": "databricks-gemma-3-12b"},
    ]}})

    assert [item.name for item in gateway_catalog(api).list_system_models().endpoints] == [
        "system.ai.gemma-3-12b"
    ]


def test_list_system_models_returns_empty_success_for_no_endpoints():
    api = RecordingApiClient(responses={LIST_PATH: {}})

    assert gateway_catalog(api).list_system_models() == SystemModelDiscovery(endpoints=())


def test_list_system_models_refuses_an_entry_without_a_name():
    api = RecordingApiClient(responses={LIST_PATH: {"endpoints": [{"id": "x"}]}})

    with pytest.raises(ModelEndpointCatalogFailure) as caught:
        gateway_catalog(api).list_system_models()
    assert caught.value.code == "catalog_unavailable"


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (PermissionDenied("PROVIDER_SECRET"), "catalog_forbidden", False),
        (DatabricksError("PROVIDER_SECRET"), "catalog_unavailable", True),
        (TimeoutError("PROVIDER_SECRET"), "catalog_unavailable", True),
        (requests.exceptions.ConnectionError("PROVIDER_SECRET"), "catalog_unavailable", True),
    ],
)
def test_list_system_models_maps_gateway_failures(error, code, retryable):
    api = RecordingApiClient(errors={LIST_PATH: error})

    with pytest.raises(ModelEndpointCatalogFailure) as caught:
        gateway_catalog(api).list_system_models()
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert "PROVIDER_SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    ("gateway", "invocable"),
    [
        ("databricks-claude-opus-5-5", "system.ai.claude-opus-5-5"),
        ("databricks-", None),
        ("claude-opus-5-5", None),
        ("xdatabricks-claude", None),
    ],
)
def test_gateway_invocable_name(gateway, invocable):
    assert gateway_invocable_name(gateway) == invocable


@pytest.mark.parametrize(
    ("model", "gateway"),
    [
        ("system.ai.claude-opus-5-5", "databricks-claude-opus-5-5"),
        ("databricks-claude-opus-4-6", "databricks-claude-opus-4-6"),
    ],
)
def test_gateway_endpoint_name(model, gateway):
    assert gateway_endpoint_name(model) == gateway
```

  Import `gateway_invocable_name` and `gateway_endpoint_name` from the module. Delete the
  old `serving_endpoints.list()` discovery tests (`:74-160` and the list half of
  `:278-292`). Keep the bounded-client tests at `:375-480` as they are.

- [ ] **Step 2: Run them and verify they fail.**

  Run: `pytest tests/unit/test_model_endpoint_catalog.py -q -k "list_system_models or gateway_"`

  Expected: FAIL, with an ImportError for `gateway_invocable_name`.

- [ ] **Step 3: Implement.** In `src/services/model_endpoint_catalog.py`:
  - change the module docstring to
    `"""Unity AI Gateway model discovery and validation for the workbench (ws2a)."""`;
  - add the constants and helpers;
  - replace `list_system_models`.

```python
GATEWAY_ENDPOINTS_PATH = "/api/ai-gateway/v2/endpoints"
GATEWAY_CHAT_API_TYPE = "mlflow/v1/chat/completions"
_GATEWAY_PREFIX = "databricks-"
_SYSTEM_AI_PREFIX = "system.ai."


def gateway_invocable_name(gateway_endpoint_name: str) -> str | None:
    """``databricks-<m>`` -> ``system.ai.<m>`` (spec §2 naming rule); otherwise ``None``."""
    if not gateway_endpoint_name.startswith(_GATEWAY_PREFIX):
        return None
    model = gateway_endpoint_name[len(_GATEWAY_PREFIX):]
    return f"{_SYSTEM_AI_PREFIX}{model}" if model else None


def gateway_endpoint_name(model_name: str) -> str:
    """``system.ai.<m>`` -> ``databricks-<m>``; any other (legacy) name is looked up as-is."""
    if model_name.startswith(_SYSTEM_AI_PREFIX):
        return f"{_GATEWAY_PREFIX}{model_name[len(_SYSTEM_AI_PREFIX):]}"
    return model_name
```

```python
    def list_system_models(self) -> SystemModelDiscovery:
        try:
            listed = self._workspace_client.api_client.do("GET", GATEWAY_ENDPOINTS_PATH)
        except PermissionDenied as error:
            raise ModelEndpointCatalogFailure(
                "catalog_forbidden",
                "Model endpoint discovery is not permitted with this workspace identity.",
                False,
            ) from error
        except (DatabricksError, *_TRANSPORT_FAILURES) as error:
            raise ModelEndpointCatalogFailure(
                "catalog_unavailable",
                "Model endpoint discovery is temporarily unavailable. Retry the request.",
                True,
            ) from error

        discovered: list[SystemModelEndpoint] = []
        for entry in (listed or {}).get("endpoints") or ():
            name = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name.strip():
                raise ModelEndpointCatalogFailure(
                    "catalog_unavailable",
                    "Model endpoint discovery returned an endpoint without a name.",
                    True,
                )
            invocable = gateway_invocable_name(name)
            if invocable is None:
                continue
            discovered.append(
                SystemModelEndpoint(name=invocable, display_name=None, description=None, docs=None)
            )

        discovered.sort(key=lambda item: item.name)
        return SystemModelDiscovery(endpoints=tuple(discovered))
```

- [ ] **Step 4: Run the tests and verify they pass.** Run
  `pytest tests/unit/test_model_endpoint_catalog.py -q`. The remote-check tests may still
  pass on the old body; Task 3 replaces them. Also run
  `pytest tests/unit/test_agent_definition_workbench_routes.py -q -k model_endpoints`. Route
  tests use `FakeModelEndpointCatalog`, whose interface is unchanged, so they must pass
  untouched.

- [ ] **Step 5: Sabotage-verify.**
  1. Make `gateway_invocable_name` return the raw name. The mapping tests must fail.
  2. Remove the `continue`. The prefix-drop test must fail.
  3. Restore both.

- [ ] **Step 6: Commit.**

```bash
git add src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py
git commit -m "feat(workbench): discover system.ai models from the Unity AI Gateway endpoint list"
```

---

### Task 3: Remote draft check through a Gateway lookup

**Files:**
- Modify: `src/services/model_endpoint_catalog.py`: the `EndpointValidationCode` Literal at
  `:16-26`, and the body of `validate_custom_endpoint_remote` at `:213-270`; drop the unused
  `EndpointStateConfigUpdate` / `EndpointStateReady` import
- Test: `tests/unit/test_model_endpoint_catalog.py`. Replace `:180-245` and the remote half
  of `:278-330`.
- Test: `tests/unit/test_graph_configuration_draft.py:3440-3520` (`_catalog_remote_validator`,
  `_endpoint_detail`, `_remote_table_cases`). Rewrite them over `RecordingApiClient`-style
  fakes.

**Interfaces:**
- Consumes: `gateway_endpoint_name`, `GATEWAY_ENDPOINTS_PATH` and `GATEWAY_CHAT_API_TYPE`
  from Task 2.
- Produces: `EndpointValidationCode` gains `"endpoint_not_gateway_model"` and
  `"endpoint_not_chat_model"`. `validate_custom_endpoint_remote(name)` keeps its signature.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_model_endpoint_catalog.py`:

```python
def detail_path(gateway_name):
    return f"{LIST_PATH}/{gateway_name}"


def test_remote_check_looks_up_the_mapped_gateway_endpoint_once():
    path = detail_path("databricks-claude-opus-5-5")
    api = RecordingApiClient(responses={path: {
        "name": "databricks-claude-opus-5-5",
        "supported_api_types": ["mlflow/v1/chat/completions", "anthropic/v1/messages"],
    }})

    assert gateway_catalog(api).validate_custom_endpoint_remote("system.ai.claude-opus-5-5") is None
    assert api.calls == [("GET", path)]


def test_remote_check_looks_up_a_legacy_name_as_is():
    path = detail_path("databricks-claude-opus-4-6")
    api = RecordingApiClient(responses={path: {
        "name": "databricks-claude-opus-4-6",
        "supported_api_types": ["mlflow/v1/chat/completions"],
    }})

    gateway_catalog(api).validate_custom_endpoint_remote("databricks-claude-opus-4-6")
    assert api.calls == [("GET", path)]


def test_remote_check_refuses_an_embedding_endpoint():
    path = detail_path("databricks-bge-large-en")
    api = RecordingApiClient(responses={path: {
        "name": "databricks-bge-large-en",
        "supported_api_types": ["mlflow/v1/embeddings"],
    }})

    with pytest.raises(EndpointValidationFailure) as caught:
        gateway_catalog(api).validate_custom_endpoint_remote("system.ai.bge-large-en")
    assert (caught.value.code, caught.value.message, caught.value.retryable) == (
        "endpoint_not_chat_model", "Endpoint is not a chat model.", False,
    )


def test_remote_check_refuses_a_detail_without_api_types():
    path = detail_path("databricks-x")
    api = RecordingApiClient(responses={path: {"name": "databricks-x"}})

    with pytest.raises(EndpointValidationFailure) as caught:
        gateway_catalog(api).validate_custom_endpoint_remote("system.ai.x")
    assert caught.value.code == "endpoint_not_chat_model"


@pytest.mark.parametrize(
    ("error", "code", "message", "retryable"),
    [
        (NotFound("PROVIDER_SECRET"), "endpoint_unknown", "Endpoint name was not found.", False),
        (PermissionDenied("PROVIDER_SECRET"), "endpoint_forbidden",
         "Endpoint cannot be validated with this workspace identity.", False),
        (DatabricksError("PROVIDER_SECRET"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
        (TimeoutError("PROVIDER_SECRET"), "endpoint_unavailable",
         "Endpoint validation is temporarily unavailable. Retry the save.", True),
    ],
)
def test_remote_check_maps_gateway_lookup_failures(error, code, message, retryable):
    api = RecordingApiClient(errors={detail_path("databricks-m"): error})

    with pytest.raises(EndpointValidationFailure) as caught:
        gateway_catalog(api).validate_custom_endpoint_remote("system.ai.m")
    assert (caught.value.code, caught.value.message, caught.value.retryable) == (code, message, retryable)
    assert "PROVIDER_SECRET" not in caught.value.message
```

  Import `NotFound` from `databricks.sdk.errors`. Keep
  `test_validate_custom_endpoint_remote_refuses_a_path_shaped_name_before_any_get` (`:362`),
  retargeted to assert `api.calls == []`.

- [ ] **Step 2: Run them and verify they fail.** Run
  `pytest tests/unit/test_model_endpoint_catalog.py -q -k remote_check`. Expected: FAIL. The
  old body calls `serving_endpoints`, which is absent.

- [ ] **Step 3: Implement.** Extend the Literal with the two codes. Replace the method body:

```python
    def validate_custom_endpoint_remote(self, name: str) -> None:
        # Defensive: never let a path-shaped name reach the interpolated request.
        validate_endpoint_name_policy(name)
        path = f"{GATEWAY_ENDPOINTS_PATH}/{gateway_endpoint_name(name)}"
        try:
            detail = self._workspace_client.api_client.do("GET", path)
        except NotFound as error:
            raise _validation_failure(
                "endpoint_unknown", "Endpoint name was not found.", False
            ) from error
        except PermissionDenied as error:
            raise _validation_failure(
                "endpoint_forbidden",
                "Endpoint cannot be validated with this workspace identity.",
                False,
            ) from error
        except (DatabricksError, *_TRANSPORT_FAILURES) as error:
            raise _validation_failure(
                "endpoint_unavailable",
                "Endpoint validation is temporarily unavailable. Retry the save.",
                True,
            ) from error

        api_types = (detail or {}).get("supported_api_types") or ()
        if GATEWAY_CHAT_API_TYPE not in api_types:
            raise _validation_failure(
                "endpoint_not_chat_model", "Endpoint is not a chat model.", False
            )
```

  `NotFound` is the SDK's 404 class. `ResourceDoesNotExist` subclasses it (probed:
  `NotFound`, `error_code` `NOT_FOUND`). Remove the
  `endpoint_name_mismatch` / `endpoint_not_ready` / `endpoint_update_*` branches. **Keep
  those codes in the Literal.** Removing Literal members could break the frontend or API
  enum consumers, so grep `frontend/src` and `src/api` for them, and record the decision in
  the corrections file.

- [ ] **Step 4: Rewrite the draft-level remote helpers** in
  `tests/unit/test_graph_configuration_draft.py`:
  - `_catalog_remote_validator` builds the catalog over
    `SimpleNamespace(api_client=<fake>)`;
  - `_remote_table_cases` covers the four failure rows and the non-chat row from Step 1,
    each asserting the saved-candidate 422 field `candidate.model.endpoint_name`;
  - the old READY/NOT_UPDATING cases are deleted and listed in the corrections file.

  Run `pytest tests/unit/test_graph_configuration_draft.py -q -k remote`.

- [ ] **Step 5: Sabotage-verify.**
  1. Drop the `supported_api_types` check. The embedding test must fail.
  2. Make `gateway_endpoint_name` identity. The mapped-lookup test must fail.
  3. Restore both.

- [ ] **Step 6: Commit.**

```bash
git add src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py tests/unit/test_graph_configuration_draft.py docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md
git commit -m "feat(workbench): validate draft models with a Unity AI Gateway lookup"
```

---

### Task 4: `system.ai` name rule on draft saves that change the model

**Files:**
- Modify: `src/services/graph_configuration_draft.py`. Add `_gateway_model_name_validator`
  near `:277`, and call it in `save_editable_model_draft` (after `:444`) and in
  `save_draft_content` (after `:503`).
- Modify: `src/services/model_endpoint_catalog.py`. Add `validate_gateway_model_name`.
- Test: `tests/unit/test_graph_configuration_draft.py`,
  `tests/unit/test_model_endpoint_catalog.py`, plus any save test whose **changed**
  endpoint name now fails.

**Interfaces:**
- Consumes: the `endpoint_not_gateway_model` code from Task 3.
- Produces: `validate_gateway_model_name(name: str) -> None`, which raises
  `EndpointValidationFailure("endpoint_not_gateway_model", ...)`.

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_model_endpoint_catalog.py`:

```python
@pytest.mark.parametrize("name", ["system.ai.claude-opus-5-5", "system.ai.gpt-oss-120b", "system.ai.a1"])
def test_validate_gateway_model_name_accepts_system_ai_names(name):
    assert validate_gateway_model_name(name) is None


@pytest.mark.parametrize("name", [
    "databricks-claude-opus-4-6", "system.ai.", "system.ai.x-", "system.ai.x.", "system.ai.x_",
    "System.AI.claude", "system.ai.Claude", "system.aiclaude", " system.ai.claude", "system.ai.a",
])
def test_validate_gateway_model_name_refuses_other_shapes(name):
    with pytest.raises(EndpointValidationFailure) as caught:
        validate_gateway_model_name(name)
    assert caught.value.code == "endpoint_not_gateway_model"
    assert caught.value.message == (
        "Model name must start with `system.ai.` and contain only lowercase letters, "
        "digits, hyphens, underscores and periods."
    )
    assert name.strip() not in caught.value.message.replace("system.ai.", "")
```

  (`system.ai.a` is refused: the regex needs at least two characters after the prefix. Write
  that in the corrections file as a deliberate consequence of spec §5.2's regex.)

  In `tests/unit/test_graph_configuration_draft.py`, parametrised over
  `SAVE_PATHS = ("editable", "trusted")` using `_endpoint_candidate` /
  `_save_endpoint_candidate`:

```python
GATEWAY_NAME_TUPLE = (
    (
        ENDPOINT_FIELD,
        "endpoint_not_gateway_model",
        "Model name must start with `system.ai.` and contain only lowercase letters, "
        "digits, hyphens, underscores and periods.",
    ),
)


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_changing_the_model_to_a_non_gateway_name_is_refused_before_any_write(
    session_factory, monkeypatch, path
):
    current, before_hash = _stored_content(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    service = _service()  # use the module's existing no-remote service builder

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        _save_endpoint_candidate(
            session, service, path,
            _endpoint_candidate(current, path, endpoint_name="databricks-claude-sonnet-4-5"),
            lock_version=0, actor="test:gateway-name",
        )

    assert _issue_tuples(caught) == GATEWAY_NAME_TUPLE
    assert write_log == []
    assert _stored_content(session_factory) == (current, before_hash)


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_changing_the_model_to_a_system_ai_name_saves(session_factory, path):
    current, _ = _stored_content(session_factory)
    service = _service()
    with session_factory() as session:
        _save_endpoint_candidate(
            session, service, path,
            _endpoint_candidate(current, path, endpoint_name="system.ai.claude-opus-5-5"),
            lock_version=0, actor="test:gateway-name",
        )
    assert _stored_content(session_factory)[0].model.endpoint_name == "system.ai.claude-opus-5-5"


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_unchanged_legacy_model_saves(session_factory, path):
    """Review Focus 2: a prompt-only edit on a databricks-* role is not blocked."""
    current, _ = _stored_content(session_factory)
    assert current.model.endpoint_name.startswith("databricks-")
    service = _service()
    with session_factory() as session:
        _save_endpoint_candidate(
            session, service, path,
            _endpoint_candidate(current, path, endpoint_name=current.model.endpoint_name,
                                prompt_text=current.prompt_text + "\nedited"),
            lock_version=0, actor="test:gateway-name",
        )
    saved, _ = _stored_content(session_factory)
    assert saved.prompt_text.endswith("\nedited")
    assert saved.model.endpoint_name == current.model.endpoint_name


def test_url_policy_still_runs_first_for_a_changed_url_shaped_name(session_factory):
    current, _ = _stored_content(session_factory)
    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        _save_endpoint_candidate(
            session, _service(), "editable",
            _endpoint_candidate(current, "editable", endpoint_name="https://x.example/serving"),
            lock_version=0, actor="test:gateway-name",
        )
    assert _issue_tuples(caught) == ENDPOINT_URL_TUPLE
```

  Use the module's real service-builder name in place of `_service()` if it differs; record
  it in the corrections file.

  In `tests/unit/test_graph_release_publication.py`, which uses its `factory` fixture,
  `_save_prompt`, `_publish` and `_backdate_v1`. Add a model-changing save helper next to
  `_save_prompt`, and the test:

```python
def _save_model(factory, agent_key, endpoint_name, *, lock):
    service = GraphConfiguration()
    with factory() as db:
        snap = service.read_workbench(db)
        db.rollback()
    content = next(n for n in snap.nodes if n.agent_key == agent_key).draft.content
    with factory() as db:
        out = service.save_editable_model_draft(
            db,
            agent_key=agent_key,
            expected_lock_version=lock,
            actor="editor@example.com",
            candidate=EditableModelDraft(
                prompt_text=content.prompt_text,
                endpoint_name=endpoint_name,
                temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens,
                top_p=float(content.model.top_p),
            ),
        )
    assert isinstance(out, DraftSaveResult)
    return out


def test_publication_with_untouched_legacy_roles_is_not_blocked(factory):
    """Review Focus 3: one role moves to system.ai.*, six stay on databricks-*, publish succeeds."""
    _backdate_v1(factory)
    _save_model(factory, "architect", "system.ai.claude-opus-5-5", lock=0)
    _save_prompt(factory, "builder", "\nlegacy-role edit", lock=1)

    outcome = _publish(factory, lock=2, gate=_NoEvidenceGate())

    assert isinstance(outcome, PublishedRelease)
```

  This mirrors `test_publish_two_changed_roles_creates_v2_with_exact_seven_mappings`
  (`:260`), which uses `_NoEvidenceGate()`, `PublishedRelease` and locks 0/1/2.

  In `tests/unit/test_graph_release_rollback.py`, use its arrange code for a published v2.
  The nearest example is the `restore_release(` call at `:927` and the fixtures it relies
  on. Copy the `_save_model` helper above into this module, since test modules do not share
  helpers here. Add a test in which v2's architect was saved with `_save_model(...,
  "system.ai.claude-opus-5-5", ...)` before publishing, and then call
  `restore_release(... version_number=1 ...)`. Use the same keyword arguments as the `:927`
  call.

```python
def test_rollback_to_a_legacy_release_is_not_blocked_by_the_gateway_name_rule(factory, monkeypatch):
    """Review Focus 1: v1 (all seven roles databricks-*) is restorable after a system.ai v2."""
    # arrange: exactly as the :927 test builds and publishes v2, with the architect's
    # model saved as "system.ai.claude-opus-5-5"
    # act: restore version 1 with the :927 call's keyword arguments
    # assert: the success type that test asserts, and
    #   the restored architect endpoint_name == "databricks-claude-opus-4-6"
```

  The three comment lines above name the exact source of each block. Replace them with code
  copied from `:927`'s test. The two assertions stated are mandatory.

- [ ] **Step 2: Run them and verify they fail.** Run
  `pytest tests/unit/test_model_endpoint_catalog.py tests/unit/test_graph_configuration_draft.py -q -k "gateway or legacy"`.
  Expected: an ImportError for `validate_gateway_model_name`, and the refusal test fails.

- [ ] **Step 3: Implement.** In `model_endpoint_catalog.py`:

```python
_GATEWAY_MODEL_NAME = re.compile(r"^system\.ai\.[a-z0-9][a-z0-9._-]*[a-z0-9]$")


def validate_gateway_model_name(name: str) -> None:
    """A changed draft model must be a ``system.ai.*`` Gateway name (spec §5.2)."""
    if not _GATEWAY_MODEL_NAME.fullmatch(name):
        raise EndpointValidationFailure(
            "endpoint_not_gateway_model",
            "Model name must start with `system.ai.` and contain only lowercase letters, "
            "digits, hyphens, underscores and periods.",
            False,
        )
```

  In `graph_configuration_draft.py`, import it and add:

```python
def _gateway_model_name_validator(
    current: DefinitionContent, candidate: DefinitionContent
) -> tuple[DraftValidationIssue, ...]:
    """ws2a: a save that CHANGES the model must name a system.ai.* Gateway model.

    Save-only by design.  It is never composed into ``_save_local_validators``,
    which publication and rollback reuse, because rollback re-validates historical
    releases whose roles name ``databricks-*`` endpoints (spec §5.2).
    """
    if candidate.model.endpoint_name == current.model.endpoint_name:
        return ()
    try:
        validate_gateway_model_name(candidate.model.endpoint_name)
    except EndpointValidationFailure as failure:
        return (_endpoint_issue(failure),)
    return ()
```

  Call it in both saves, immediately after the existing `_save_local_validators()` run,
  against the locked current content:

```python
            self._run_candidate_validators(self._save_local_validators(), content)
            gateway_issues = _gateway_model_name_validator(
                locked.selected.draft.content, content
            )
            if gateway_issues:
                raise DraftContentRejected(*gateway_issues)
```

  In `save_draft_content`, use `validated` in place of `content`.

  **Ordering check:** the existing URL policy runs inside `_save_local_validators()`, so a
  URL-shaped name reports `endpoint_url_not_allowed` first and the save stops there. The
  Step 1 URL test pins this.

- [ ] **Step 4: Fix the fixtures that changed the model to a made-up name.** Run
  `pytest tests/unit -q`. Also run each PostgreSQL integration file that saves drafts, one
  at a time, with `TELLR_TEST_POSTGRES_URL` set:
  - `tests/integration/test_agent_definition_workbench_postgres.py`
  - `tests/integration/graph_lifecycle_journey.py` (via its runner)
  - `tests/integration/test_graph_release_publication_acceptance_postgres.py`
  - `tests/integration/test_graph_release_rollback_acceptance_postgres.py`

  For each new `endpoint_not_gateway_model` failure where the test **intends** to change the
  model, change the fixture's new name to a `system.ai.*` name. For example, `CUSTOM_ENDPOINT
  = "custom endpoint name"` becomes `"system.ai.custom-endpoint-name"`, and `"endpoint-a2"`
  becomes `"system.ai.endpoint-a2"`. **Never change an assertion's expected code or remove an
  assertion.** Where a test asserts the stored name, update the expected value to the same
  new literal. List every fixture edit in the corrections file.

- [ ] **Step 5: Run everything touched.**

```bash
pytest tests/unit -q
```

  Then run each PostgreSQL file above. Expected: only baseline-cause failures remain.

- [ ] **Step 6: Sabotage-verify.**
  1. Remove the `== current` early return. `test_unchanged_legacy_model_saves` must fail.
  2. Compose the validator into `_save_local_validators` instead. The rollback test must
     fail.
  3. Restore both.

- [ ] **Step 7: Commit.**

```bash
git add src/services/graph_configuration_draft.py src/services/model_endpoint_catalog.py tests/ docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md
git commit -m "feat(workbench): require a system.ai model when a draft save changes the model"
```

---

### Task 5: Export converters through the Gateway

**Files:**
- Create: `src/services/gateway_openai.py`
- Modify: `src/services/html_to_pptx.py:51,63,75`, `src/services/html_to_google_slides.py:342,358`
- Test: `tests/unit/test_gateway_openai.py` (new), `tests/unit/test_html_to_pptx.py`, `tests/unit/test_google_slides_converter.py`

**Interfaces:**
- Produces: `gateway_openai_client(workspace_client) -> openai.OpenAI`, which returns
  `DatabricksOpenAI(workspace_client=..., use_ai_gateway=True)`.

- [ ] **Step 1: Write the failing tests.** Create `tests/unit/test_gateway_openai.py`:

```python
import json

from tests.fixtures.mock_chat_completions import MockChatCompletionsWorkspace, install_mock_gateway_transport

from src.services.gateway_openai import gateway_openai_client


def test_gateway_openai_client_posts_to_the_gateway_chat_route(monkeypatch):
    install_mock_gateway_transport(monkeypatch)
    workspace = MockChatCompletionsWorkspace({}, usage=None)
    workspace._handle = _text_handler(workspace)

    client = gateway_openai_client(workspace)
    client.chat.completions.create(model="system.ai.claude-sonnet-4-5",
                                   messages=[{"role": "user", "content": "hi"}], max_tokens=5)

    request = workspace.requests[0]
    assert request.url.path == "/ai-gateway/mlflow/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"
    assert json.loads(request.content)["model"] == "system.ai.claude-sonnet-4-5"


def _text_handler(workspace):
    import httpx

    def handle(request):
        workspace.requests.append(request)
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
        })

    return handle
```

  In `tests/unit/test_html_to_pptx.py` (and the matching Google Slides test module):

```python
#: The shape recorded through the Gateway on 2026-09-28 (spec §2).
GATEWAY_THINKING_CONTENT = [
    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking...", "signature": "sig"}]},
    {"type": "text", "text": "```python\nprint(\"hello\")\n```"},
]


def test_extract_text_content_takes_only_the_text_block_of_a_gateway_thinking_reply():
    assert HtmlToPptxConverterV3._extract_text_content(GATEWAY_THINKING_CONTENT) == '```python\nprint("hello")\n```'


def test_converter_defaults_to_the_gateway_model_and_client(monkeypatch):
    sentinel_client = object()
    seen = []
    monkeypatch.setattr("src.services.html_to_pptx.gateway_openai_client",
                        lambda ws: seen.append(ws) or sentinel_client)
    workspace = object()

    converter = HtmlToPptxConverterV3(workspace_client=workspace)

    assert converter.model_endpoint == "system.ai.claude-sonnet-4-5"
    assert converter.llm_client is sentinel_client
    assert seen == [workspace]
```

  Write the Google Slides equivalents against `HtmlToGoogleSlidesConverter`. Pass a stub
  `google_auth=object()` so no Google auth is built. Check its content parser's name, around
  `html_to_google_slides.py:850`, and use it.

- [ ] **Step 2: Run them and verify they fail.** Run
  `pytest tests/unit/test_gateway_openai.py tests/unit/test_html_to_pptx.py tests/unit/test_google_slides_converter.py -q -k "gateway"`.
  Expected: an ImportError, and the model is still `databricks-claude-sonnet-4-5`.

- [ ] **Step 3: Implement.** Create `src/services/gateway_openai.py`:

```python
"""The one OpenAI-compatible client for app LLM calls through Unity AI Gateway (ws2a)."""

from __future__ import annotations

from typing import Any


def gateway_openai_client(workspace_client: Any) -> Any:
    """``DatabricksOpenAI`` bound to ``{host}/ai-gateway/mlflow/v1`` with the caller's identity."""
    from databricks_openai import DatabricksOpenAI

    return DatabricksOpenAI(workspace_client=workspace_client, use_ai_gateway=True)
```

  In both converters:
  - `DEFAULT_MODEL = "system.ai.claude-sonnet-4-5"`;
  - `self.llm_client = gateway_openai_client(self.ws_client)`, with
    `from src.services.gateway_openai import gateway_openai_client` at module top;
  - in `html_to_pptx.py:63`, the docstring default becomes
    `(default: system.ai.claude-sonnet-4-5)`.

  The identity is unchanged: `ws_client` is the app service principal
  (`get_databricks_client()`).

- [ ] **Step 4: Run the tests and verify they pass.** Run the three modules, plus
  `tests/unit/test_google_slides_routes.py` and `tests/unit/test_pptx_runner.py`.

- [ ] **Step 5: Sabotage-verify.**
  1. Drop `use_ai_gateway=True`. The route-path test must fail.
  2. Restore the old `DEFAULT_MODEL`. The default test must fail.
  3. Restore both.

- [ ] **Step 6: Commit.**

```bash
git add src/services/gateway_openai.py src/services/html_to_pptx.py src/services/html_to_google_slides.py tests/unit/test_gateway_openai.py tests/unit/test_html_to_pptx.py tests/unit/test_google_slides_converter.py
git commit -m "feat(export): call the converter model through Unity AI Gateway"
```

---

### Task 6: Session titles through the Gateway (OBO)

**Files:**
- Modify: `src/core/defaults.py` (add `SESSION_TITLE_MODEL`), `src/api/services/session_naming.py` (add `build_session_title_model`), `src/api/services/chat_service.py:1447-1458` and `:2002-2012`
- Test: `tests/unit/test_session_naming.py`

**Interfaces:**
- Produces: `build_session_title_model() -> ChatDatabricks`, constructed with
  `model=SESSION_TITLE_MODEL, use_ai_gateway=True, max_tokens=50, temperature=0.3, workspace_client=get_user_client()`.

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_session_naming.py`:

```python
class TestBuildSessionTitleModel:
    def test_builds_the_gateway_title_model_as_the_user(self, monkeypatch):
        import databricks_langchain

        from src.api.services import session_naming

        constructed = []
        user_client = object()
        monkeypatch.setattr(databricks_langchain, "ChatDatabricks", lambda **kw: constructed.append(kw) or "model")
        monkeypatch.setattr("src.core.databricks_client.get_user_client", lambda: user_client)

        assert session_naming.build_session_title_model() == "model"
        assert constructed == [{
            "model": "system.ai.claude-opus-4-6",
            "use_ai_gateway": True,
            "max_tokens": 50,
            "temperature": 0.3,
            "workspace_client": user_client,
        }]

    def test_both_chat_service_title_sites_use_the_helper(self):
        import inspect

        from src.api.services import chat_service

        source = inspect.getsource(chat_service)
        assert source.count("build_session_title_model()") == 2
        assert 'DEFAULT_CONFIG["llm"]["endpoint"],\n                    max_tokens=50' not in source
        assert "max_tokens=50" not in source
```

- [ ] **Step 2: Run them and verify they fail.**

  Run: `pytest tests/unit/test_session_naming.py -q -k BuildSessionTitleModel`

  Expected: FAIL, with `AttributeError: build_session_title_model`.

- [ ] **Step 3: Implement.**
  - In `src/core/defaults.py`, below `DEFAULT_CONFIG`:

```python
#: Session-title generation (both engine paths) goes through Unity AI Gateway (ws2a).
#: Kept separate from DEFAULT_CONFIG["llm"], which the out-of-scope monolith still reads.
SESSION_TITLE_MODEL = "system.ai.claude-opus-4-6"
```

  - In `src/api/services/session_naming.py`:

```python
def build_session_title_model():
    """The title model: Gateway-routed, on the requesting user's OBO identity."""
    from databricks_langchain import ChatDatabricks

    from src.core.databricks_client import get_user_client
    from src.core.defaults import SESSION_TITLE_MODEL

    return ChatDatabricks(
        model=SESSION_TITLE_MODEL,
        use_ai_gateway=True,
        max_tokens=50,
        temperature=0.3,
        workspace_client=get_user_client(),
    )
```

  - In both `chat_service.py` sites, replace the `ChatDatabricks(...)` construction and its
    three local imports with:

```python
                from src.api.services.session_naming import build_session_title_model

                naming_model = build_session_title_model()
```

  Keep the surrounding `try`/`except`, the rename and the logging exactly as they are.

- [ ] **Step 4: Run the tests and verify they pass.** Run
  `pytest tests/unit/test_session_naming.py tests/unit/test_chat_service_no_singleton.py -q`,
  and grep `tests/` for other tests that patch `ChatDatabricks` in `chat_service` for titles.
  Retarget them to `session_naming.build_session_title_model` without removing assertions,
  and list them in the corrections file.

- [ ] **Step 5: Sabotage-verify.**
  1. Change `use_ai_gateway=True` to `False`. The construction test must fail.
  2. Inline one site back. The site-count test must fail.
  3. Restore both.

- [ ] **Step 6: Commit.**

```bash
git add src/core/defaults.py src/api/services/session_naming.py src/api/services/chat_service.py tests/unit/test_session_naming.py
git commit -m "feat(titles): generate session titles through Unity AI Gateway"
```

---

### Task 7: Workbench picker — list only, no custom name

**Files:**
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx:526-541`
- Test: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`
  (helper `customEndpoint()` at `:2259`, and uses at `:339`, `:509`, `:661`, `:897`, `:947`,
  `:2326-2341`, `:2632`, `:3209`)

**Interfaces:**
- Consumes: `GET /api/admin/agent-definitions/model-endpoints`, which now returns
  `system.ai.*` names (Tasks 2 and 3). No API shape change.

- [ ] **Step 1: Write the failing tests.** In `AgentDefinitionWorkbench.test.tsx`, add them
  next to the discovery tests (`:2326`), using the file's existing render and discovery-mock
  helpers:

```tsx
  it('offers no free-text endpoint field', async () => {
    mockWorkbenchWithPuts(() => apiResponse(500, null));
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();

    await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    expect(within(panel).queryByRole('textbox', { name: 'Custom endpoint name' })).toBeNull();
  });

  it('shows the current model when it is not in the discovered list', async () => {
    // Discovery returns only system.ai names; the seed role is on SEED_MODEL_ENDPOINT_NAME.
    mockWorkbenchWithPuts(() => apiResponse(500, null), {
      models: syntheticSystemModelEndpoints.filter((item) => item.name !== SEED_MODEL_ENDPOINT_NAME),
    });
    render(<AgentDefinitionWorkbench />);
    await loadedNodeNavigation();
    const panel = openModelTab();

    const group = await within(panel).findByRole('radiogroup', { name: 'Discovered models' });
    expect(within(panel).getByText('Current model')).toBeInTheDocument();
    expect(within(panel).getByText(SEED_MODEL_ENDPOINT_NAME)).toBeInTheDocument();
    expect(within(group).queryAllByRole('radio').filter((radio) => (radio as HTMLInputElement).checked)).toHaveLength(0);
  });
```

  **Check `mockWorkbenchWithPuts`.** If it does not accept a discovery override, find how
  the existing tests vary the discovery response. Search the file for
  `syntheticSystemModelEndpoints` and `catalogGets`, and use that mechanism instead. Record
  the helper you used in the corrections file.

  **The endpoint-error test is a move, not a new test.** At `:897`, change
  `screen.getByRole('textbox', { name: 'Custom endpoint name' })` to
  `screen.getByRole('radiogroup', { name: 'Discovered models' })`. Keep
  `.toHaveAccessibleDescription('Endpoint rejected.')` unchanged. It fails before Step 3,
  because the radiogroup has no description yet.

- [ ] **Step 2: Run them and verify they fail.**

  Run: `cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`

  Expected: the three new tests fail. `npx vitest` runs the already-installed binary. **Do
  not run `npm install`.**

- [ ] **Step 3: Implement.** In `DefinitionEditor.tsx`:
  - Delete the "Advanced" / "Custom endpoint name" block (`:526-541`).
  - Directly above the radiogroup, add:

```tsx
          <p className="text-xs text-gray-600">
            <span className="font-semibold">Current model</span>{' '}
            <span className="break-all font-mono">{entry.local.endpoint_name}</span>
          </p>
```

  - Give the radiogroup
    `aria-describedby={endpointMessage ? `${agentKey}-endpoint-error` : undefined}`.
  - Render `<FieldError id={`${agentKey}-endpoint-error`} message={endpointMessage} />`
    immediately after it, **outside** the `visibleModels.length > 0` condition, so the error
    still shows when discovery returns nothing.

- [ ] **Step 4: Migrate the existing tests.** Every test that **typed** into the custom field
  now selects a radio for the same name. First add that name to the mocked discovery
  response, as a `system.ai.*` name matching the Task 4 fixture renames. Every test that
  **read** the field's value now reads the "Current model" text, or the checked radio. Update
  the label inventory at `:3209`: remove `'Custom endpoint name'`. Never delete a behavioural
  assertion; move it to the new element. List the migrated tests in the corrections file.

- [ ] **Step 5: Run the tests and typecheck.**

```bash
cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench && npx tsc --noEmit
```

  Expected: all pass, with no type errors.

- [ ] **Step 6: Sabotage-verify.** Temporarily put the custom field back. "offers no
  free-text endpoint field" must fail. Restore it.

- [ ] **Step 7: Commit.**

```bash
git add frontend/src/components/Admin/AgentDefinitionWorkbench/
git commit -m "feat(workbench-ui): pick models only from the Gateway list; show the current model"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-tellr-agentic-rebuild-prd-design.md` (§3 status, §8.1 status, §10 row 2)
- Modify: `docs/superpowers/plans/2026-09-28-ws2-ai-gateway-HANDOVER.md` (§2 table)
- Modify: `docs/technical/backend-overview.md` (workbench model selection)

- [ ] **Step 1: Update the PRD.** In §10, split row 2 into:
  - **2a**: "Unity AI Gateway routing for the graph, export and titles; the workbench takes
    `system.ai.*` models from the Gateway list". Link the spec and this plan. Status: ✅
    once Task 9 passes.
  - **2b**: "attribution, token and cost capture, dashboard, rate limits and 429 UX, request
    tags, remaining call sites (monolith, MCP, judge, feedback, validator), configurable
    export and title models". Status: ⏭️. Its starting reference is the handover.

  In §8.1 and in §3's platform-status paragraph, add a dated 2026-09-28 note saying what 2a
  delivered and what remains for 2b. Hardcoded endpoints remain in the monolith, MCP, judge
  and feedback. Export and titles now use Gateway-named constants.

- [ ] **Step 2: Update the handover.** In the §2 table, mark G1–G3, X1/X2 and T1/T2 as
  "→ Gateway (ws2a)". Mark the rest "unchanged, ws2b".

- [ ] **Step 3: Update `docs/technical/backend-overview.md`.** Where it describes model
  endpoint discovery and validation, replace the serving-endpoint description with:
  - discovery reads `GET /api/ai-gateway/v2/endpoints` and maps `databricks-X` →
    `system.ai.X`;
  - there are no custom names;
  - the remote check is a Gateway lookup that requires `mlflow/v1/chat/completions`;
  - changing a model requires a `system.ai.*` name;
  - legacy names on stored releases keep working.

- [ ] **Step 4: Commit.**

```bash
git add docs/
git commit -m "docs: record workstream 2a (AI Gateway routing) and split out 2b"
```

---

### Task 9: Live acceptance on devloop

**Files:** none. Record the results in the corrections file.

- [ ] **Step 1: Publish and deploy.** Confirm the push with the user first. Then use the
  `deploy-tellr-dev` skill: push, run `gh workflow run publish-dev.yml --ref feat/ws2a-ai-gateway`,
  and run
  `./scripts/deploy_local.sh update --env devloop --instance ws2a --profile tellr-dev --from-pypi <version>`.

- [ ] **Step 2: OBO titles, which is the stop condition.** Start a new session and send one
  message. The session must get a generated title, not the default. **If it does not, stop
  and report to the user.** Titles may be failing silently under OBO. The fallback is a user
  decision (spec §4).

- [ ] **Step 3: Workbench.** Open `/admin` → Agent Definitions.
  - The picker lists `system.ai.*` names only, and there is no custom field.
  - Pick `system.ai.claude-opus-5-5` for the architect, save it and run "Test structured
    output": it must pass.
  - Pick `system.ai.bge-large-en`, then save: the save must be refused with "Endpoint is not
    a chat model."

- [ ] **Step 4: Publish and run.** Publish the draft. A **new** conversation completes a
  graph turn and produces slides.

- [ ] **Step 5: Legacy pin.** A conversation that started **before** the publish, and so is
  pinned to the seeded release, still completes a turn.

- [ ] **Step 6: Export.** PPTX export and Google Slides export each succeed on the new deck.

- [ ] **Step 7: Rollback.** Roll back to the seeded release from `/admin`: it must succeed.
  Then roll forward again.

- [ ] **Step 8: Record and commit.** Record each result, with its timestamp, in the
  corrections file, and commit it:
  `docs(plan): ws2a live acceptance results`.
