# ws2a — Tasks 5–9

Part of `2026-09-28-ws2a-ai-gateway.md` (index: goal, global constraints, review focus, file map). Read the index first; its Global Constraints apply to every task here. Tasks 0–4 (`2026-09-28-ws2a-ai-gateway-tasks-0-4.md`) must be complete before these start.

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
