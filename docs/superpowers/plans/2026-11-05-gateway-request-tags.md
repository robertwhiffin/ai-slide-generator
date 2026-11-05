# Gateway Request Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Load `executing-plans-tellr` alongside it (CLAUDE.md). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Tellr LLM call that goes through Unity AI Gateway carries `Databricks-Ai-Gateway-Request-Tags: {"source": "tellr"}` and a `tellr/<version>` User-Agent, so Databricks can attribute customer Gateway spend to Tellr from `system.ai_gateway.usage`.

**Architecture:** One helper, `gateway_request_headers()`, builds the two headers. The three Gateway client construction sites send them: the export client (`DatabricksOpenAI`) via `default_headers`; the two `ChatDatabricks` sites (graph agents, session titles) via `extra_params={"extra_headers": ...}`, which `ChatDatabricks._prepare_inputs` spreads into `client.chat.completions.create(**data)` — the OpenAI SDK turns `extra_headers` into request headers. A source-scan test pins the set of Gateway construction sites so a new one cannot ship untagged.

**Tech Stack:** Python 3.11, databricks-langchain 0.21.0 (`ChatDatabricks`), databricks-openai 0.17.1 (`DatabricksOpenAI`), openai 3.26.1, pytest + `httpx.MockTransport` (`tests/fixtures/mock_chat_completions.py`).

**Spec:** the Design section below — agreed in chat on 2026-11-05 (small change; no separate spec doc). Origin: a teammate's Slack proposal; prior art is Isaac CLI (`{"source":"isaac-cli"}`) and databricks-vscode PR #2247 (`{"source":"databricks-vscode"}` + `databricks-vscode/<version>` UA).

## Design (agreed)

- **Purpose:** internal reporting/attribution only — Databricks counts customers and tokens per workspace by filtering `system.ai_gateway.usage` on `request_tags['source'] = 'tellr'`. Reporting job/dashboard is out of scope (the teammate's side).
- **Tag content:** exactly `{"source": "tellr"}`. No per-agent, per-user, per-deck or version tags.
- **User-Agent:** `tellr/<version> OpenAI/Python <openai version>` (orchestrator's call, user did not object): product first, the SDK's own UA kept after it, as Isaac's `ucode/<v> claude/<v>` does.
- **In scope:** the three Gateway call sites — graph agents (`DatabricksModelAdapter._default_model_factory`, `src/services/agent_runtime.py:535-540`; also reached by the #266 probe and #267 workbench), session titles (`build_session_title_model`, `src/api/services/session_naming.py:112-117`), PPTX + Google Slides export (`gateway_openai_client`, `src/services/gateway_openai.py:8-12`).
- **Out of scope:** every `/serving-endpoints` path (legacy monolith `agent_factory.py`/`agent.py`, `feedback_service.py`, `config_validator.py`, `evaluation/llm_judge.py`) — an undercount is acceptable, graph agents are ~99% of spend; Genie One / Gateway MCP calls (`mcp_transport.py`) — no token spend, and the docs don't say tags are accepted on MCP routes.
- **Done:** devloop deploy where deck generation, a title and a PPTX export all succeed (proves the real Gateway accepts the header), then rows with `request_tags['source'] = 'tellr'` in that workspace's `system.ai_gateway.usage`; then a PR.

## Global Constraints

- Header name exactly `Databricks-Ai-Gateway-Request-Tags`; value exactly `json.dumps({"source": "tellr"})`, i.e. `{"source": "tellr"}`.
- User-Agent key spelled `User-Agent` (Task 1 ruling: the OpenAI SDK merges headers case-insensitively, so casing cannot send two UAs; the one-UA assertion stays as a guard). Value exactly `f"tellr/{_get_package_version()} OpenAI/Python {openai.__version__}"`, `_get_package_version` from `src/core/databricks_client.py`.
- **Do not touch how Databricks SDK clients are created.** `src/core/databricks_client.py` must have an empty diff: its `product=` / `product_version=` tags (`tellr-app-system`, `tellr-app-<hash>`) on SDK requests are how installs are tracked. The new headers go only on OpenAI-client requests to `/ai-gateway/...`.
- No new dependencies. Python env is the per-worktree uv `.venv`; run everything via `uv run` (never `pip install`).
- Baseline (2026-11-05, before Task 1): `uv run pytest tests/unit/test_gateway_openai.py tests/unit/test_session_naming.py tests/unit/test_agent_runtime.py tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_model_endpoint_probe.py tests/unit/test_html_to_pptx.py tests/unit/test_google_slides_converter.py -q` → `349 passed`. Compare failures by cause, not count.
- Commits end with `Co-authored-by: Isaac <no-reply@databricks.com>`.

## Review Focus

1. **`extra_headers` / `extra_params` leaking into the JSON body** — the Gateway would 400 every graph call. Expect: they appear only as headers; the body has neither key. Pinned in Task 2 (adapter and title wire tests assert both keys absent from the body).
2. **Two User-Agent values on the wire** (a case-mismatched key adds instead of replacing). Expect exactly one UA. Pinned in Tasks 1 and 2 via `request.headers.get_list("user-agent") == [EXPECTED_UA]`.
3. **Later tool-loop rounds losing the header** (each round re-invokes the bound model). Expect every request of a multi-round `invoke_with_tools` to carry both headers. Pinned in Task 2's tool-loop test.
4. **A future Gateway client built without the helper** (Isaac's actual failure: its tag was silently dropped by a header rewrite, unity-gateway PR #974). Expect a test failure. Pinned in Task 2's source-scan guard.
5. **The real Gateway rejecting or ignoring the header** (behaviour on these headers is undocumented). Expect calls to succeed and rows to be recorded with the tag. Only a live run proves it: Task 3.

---

### Task 1: Header helper + export client

**Models:** `test=opus impl=haiku` (values are pinned exactly; reviewer = sonnet)

**Files:**
- Create: `src/services/gateway_headers.py`
- Modify: `src/services/gateway_openai.py:8-12`
- Test: `tests/unit/test_gateway_headers.py` (create), `tests/unit/test_gateway_openai.py` (add one test)

**Interfaces:**
- Consumes: `src.core.databricks_client._get_package_version() -> str` (read-only; do not modify that module).
- Produces:
  - `REQUEST_TAGS_HEADER: Final[str] = "Databricks-Ai-Gateway-Request-Tags"`
  - `def gateway_request_headers() -> dict[str, str]` — returns a **new** dict each call with exactly two keys, `REQUEST_TAGS_HEADER` and `"User-Agent"`, values per Global Constraints.
  - `gateway_openai_client(workspace_client)` unchanged signature; now sends both headers on every request.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_gateway_headers.py`:

```python
import json
import openai
from src.core.databricks_client import _get_package_version
from src.services.gateway_headers import REQUEST_TAGS_HEADER, gateway_request_headers

EXPECTED_UA = f"tellr/{_get_package_version()} OpenAI/Python {openai.__version__}"

def test_request_tags_header_is_the_source_tellr_json_object():
    assert REQUEST_TAGS_HEADER == "Databricks-Ai-Gateway-Request-Tags"
    assert json.loads(gateway_request_headers()[REQUEST_TAGS_HEADER]) == {"source": "tellr"}

def test_user_agent_leads_with_tellr_and_keeps_the_openai_sdk():
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA

def test_only_the_tag_and_user_agent_are_set():
    assert set(gateway_request_headers()) == {REQUEST_TAGS_HEADER, "User-Agent"}

def test_each_call_returns_a_fresh_dict():
    first = gateway_request_headers()
    first["User-Agent"] = "mutated"
    assert gateway_request_headers()["User-Agent"] == EXPECTED_UA
```

Add to `tests/unit/test_gateway_openai.py` (reuse its `_text_handler`):

```python
def test_gateway_openai_client_sends_the_tellr_tag_and_user_agent(monkeypatch):
    # same setup + create() call as the existing route test
    request = workspace.requests[0]
    assert request.headers.get_list("databricks-ai-gateway-request-tags") == ['{"source": "tellr"}']
    assert request.headers.get_list("user-agent") == [EXPECTED_UA]
    assert request.headers["authorization"] == "Bearer unit-test-dummy-key"
```

In every test file, compute `EXPECTED_UA` with the same recipe as `test_gateway_headers.py` (`_get_package_version()` + `openai.__version__`); never hard-code a version string.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_gateway_headers.py tests/unit/test_gateway_openai.py -v`
Expected: `test_gateway_headers.py` errors on collection (`ModuleNotFoundError: No module named 'src.services.gateway_headers'`); the new export test FAILS on the missing tag header (`[] == ['{"source": "tellr"}']`); the existing route test PASSES.

- [ ] **Step 3: Implement `gateway_request_headers() -> dict[str, str]` in `src/services/gateway_headers.py`; pass `default_headers=gateway_request_headers()` to `DatabricksOpenAI(...)` in `gateway_openai_client`**

Import `_get_package_version` inside the function (keeps the module import-light, like the call sites' lazy client imports). Module docstring: one paragraph saying what the headers are for (internal attribution via `system.ai_gateway.usage`) and that SDK clients are deliberately untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_gateway_headers.py tests/unit/test_gateway_openai.py tests/unit/test_html_to_pptx.py tests/unit/test_google_slides_converter.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/gateway_headers.py src/services/gateway_openai.py tests/unit/test_gateway_headers.py tests/unit/test_gateway_openai.py
git commit -m "feat(gateway): tag export LLM calls with source=tellr and a tellr user agent"
```

---

### Task 2: Tag the ChatDatabricks paths (graph agents, session titles) + site guard

**Models:** `test=opus impl=sonnet` (reviewer = opus)

**Files:**
- Modify: `src/services/agent_runtime.py:535-540` (`_default_model_factory`)
- Modify: `src/api/services/session_naming.py:112-117` (`build_session_title_model`)
- Test: `tests/unit/test_agent_runtime.py`, `tests/unit/test_agent_runtime_tool_loop.py`, `tests/unit/test_session_naming.py`, `tests/unit/test_gateway_headers.py`

**Interfaces:**
- Consumes: `gateway_request_headers()` and `REQUEST_TAGS_HEADER` from Task 1.
- Produces: no new names. `_default_model_factory(**kwargs)` and `build_session_title_model()` keep their signatures; each now constructs `ChatDatabricks(..., extra_params={"extra_headers": gateway_request_headers()})`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_agent_runtime.py` — next to `test_production_adapter_sends_the_stored_name_to_the_gateway_chat_route`, same setup (`install_mock_gateway_transport`, `MockChatCompletionsWorkspace(fake_output("architect"), usage=None)`, `DatabricksModelAdapter(client_factory=lambda: workspace)`, one `adapter.invoke(...)`):

```python
def test_production_adapter_sends_the_tellr_tag_and_user_agent(monkeypatch):
    ...
    request = workspace.requests[0]
    assert request.headers.get_list("databricks-ai-gateway-request-tags") == ['{"source": "tellr"}']
    assert request.headers.get_list("user-agent") == [EXPECTED_UA]
    sent = json.loads(request.content)
    assert "extra_headers" not in sent and "extra_params" not in sent
```

`tests/unit/test_agent_runtime_tool_loop.py` — `test_every_tool_loop_round_carries_the_tellr_tag`: the same two-round script as `test_the_real_provider_client_accepts_the_tools_and_the_tool_result_history`; assert `len(workspace.requests) == 2` and, for **each** request, the tag `get_list` and UA `get_list` assertions above.

`tests/unit/test_session_naming.py`:
- Update `test_builds_the_gateway_title_model_as_the_service_principal`: the expected `constructed` dict gains `"extra_params": {"extra_headers": gateway_request_headers()}`; everything else in it unchanged.
- Add `test_title_model_sends_the_tellr_tag_and_user_agent`: `install_mock_gateway_transport`; a `MockChatCompletionsWorkspace` whose `_handle` returns a plain text completion (like `_text_handler` in `test_gateway_openai.py`); patch `src.core.databricks_client.get_system_client` to return it; `build_session_title_model().invoke("hi")`; assert the tag `get_list`, UA `get_list`, and neither `extra_headers` nor `extra_params` in the JSON body.

`tests/unit/test_gateway_headers.py`:

```python
def test_every_gateway_client_construction_sends_the_tellr_headers():
    """Isaac's tag was once silently dropped; a new Gateway client must not ship untagged."""
    src = Path(__file__).resolve().parents[2] / "src"
    sites = {p.relative_to(src).as_posix() for p in src.rglob("*.py")
             if "use_ai_gateway" in p.read_text()}  # also catches use_ai_gateway_native_api
    assert sites == {"services/agent_runtime.py", "api/services/session_naming.py", "services/gateway_openai.py"}
    for site in sites:
        assert "gateway_request_headers()" in (src / site).read_text(), site
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_agent_runtime.py tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_session_naming.py tests/unit/test_gateway_headers.py -v`
Expected: the five new/updated tests FAIL on missing headers / missing `extra_params` / the guard's `gateway_request_headers()` check for the two `ChatDatabricks` files; all others PASS.

- [ ] **Step 3: Pass `extra_params={"extra_headers": gateway_request_headers()}` to `ChatDatabricks` in `_default_model_factory` and in `build_session_title_model`**

Import `gateway_request_headers` lazily beside each site's existing lazy `ChatDatabricks` import. Do not route it through `transport_options` (that is the admin-request timeout/retry bound and must stay exactly as is). Extend the comment at `agent_runtime.py:538-539` by one line saying the headers are Tellr's Gateway attribution tag.

- [ ] **Step 4: Run tests to verify they pass, then the baseline set**

Run: `uv run pytest tests/unit/test_agent_runtime.py tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_session_naming.py tests/unit/test_gateway_headers.py tests/unit/test_model_endpoint_probe.py tests/unit/test_gateway_openai.py tests/unit/test_html_to_pptx.py tests/unit/test_google_slides_converter.py -q`
Expected: all PASS (baseline 349 + the new tests). `git diff origin/main -- src/core/databricks_client.py` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add src/services/agent_runtime.py src/api/services/session_naming.py tests/unit/test_agent_runtime.py tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_session_naming.py tests/unit/test_gateway_headers.py
git commit -m "feat(gateway): tag graph-agent and session-title LLM calls with source=tellr"
```

---

### Task 3: Live Gateway check on devloop, then PR

**Models:** `test=— impl=opus` — run by the orchestrator, not dispatched: the check is the real Gateway, there is no test to author.

Load `deploy-tellr-dev`, and `databricks-core` + `databricks-dbsql` for the query. Always `--profile tellr-dev`; never `devtest`.

- [ ] **Step 1: Full unit suite** — `uv run pytest tests/unit -q -n auto`. For each failure, check it fails the same way on `origin/main` (same cause, not just same count); any failure this branch introduced stops the task.
- [ ] **Step 2: Publish a dev wheel** — `git push origin feat/gateway-request-tags` (personal `robertwhiffin` account, never EMU); `gh workflow run publish-dev.yml --ref feat/gateway-request-tags`; record the published `.devN` version.
- [ ] **Step 3: Deploy** — `./scripts/deploy_local.sh create --env devloop --instance gw-tags --profile tellr-dev --from-pypi <version>`. On `RESOURCE_EXHAUSTED` (account SP limit) stop and ask the user before deleting any app.
- [ ] **Step 4: Exercise all three paths in the app** — create a deck (graph turn succeeds; slides render), confirm the deck gets an auto title, export it to PPTX. All three succeeding = the Gateway accepts the headers. Any 4xx from `/ai-gateway/` is a stop.
- [ ] **Step 5: Confirm attribution (≥1 h after Step 4; records typically land within an hour)** — on a tellr-dev SQL warehouse:

```sql
SELECT user_agent, request_tags['source'] AS source, requester,
       count(*) AS requests, sum(total_tokens) AS tokens
FROM system.ai_gateway.usage
WHERE event_time >= current_timestamp() - INTERVAL 6 HOURS
  AND request_tags['source'] = 'tellr'
GROUP BY ALL
```

(`request_tags` is a MAP and cannot be grouped on; select the key.) Expected: ≥1 row, `user_agent` starting `tellr/<version> OpenAI/Python`, `source = 'tellr'`. No rows after 3 h = stop and report.
- [ ] **Step 6: PR** — body written with `mattpocock-skills:pr`; include the Step 5 result, the out-of-scope list from the Design section, and a note for the reporting side that Databricks-internal workspaces (dev, evals) also emit `source=tellr` and should be excluded. End the body with `This pull request and its description were written by Isaac.`
- [ ] **Step 7: After merge** — delete devloop `gw-tags`, remove the worktree, update memory `gateway-request-tags`.
