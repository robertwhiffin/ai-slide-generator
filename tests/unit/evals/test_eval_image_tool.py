"""Chat image generation, Task 9 (eval parity): the offline eval harness learns the architect's
``generate_image`` tool. Offline: no model endpoint, no workspace, no network.

Names this file fixes for the implementer:

* **The opt-in.** ``AgentEvalConfig.image_tool: bool = False``, read from the YAML key
  ``image_tool`` (a bool; only for the roles in ``config.IMAGE_TOOL_ROLES``, the architect). It
  changes no definition content, so the content hash stays the v1 one. The committed config is
  ``evals/configs/architect/image-tool.yaml``.
* **The binding.** ``Runner.run`` keeps its signature. An opted-in architect run gets production's
  ``ImageGenerationAgentTool`` (its name, description and args schema) on a toolset of
  production's first-pass budget (``MAX_CALLS_PER_TURN`` calls, ``BUDGET_SECONDS`` seconds),
  through ``_RUN_TOOLSET`` and ``_ToolLoopAdapter`` as the brand search is, a fresh one per
  attempt. Only its backends are fake: ``generator_factory`` answers with a small valid image of
  the preset's format, ``save`` returns a fresh ``secrets.token_urlsafe(32)``-shaped token.
  Every other run binds nothing, exactly as before.
* **The record** (``RunResult.tool_calls``), one entry per image call the tool started (its
  ``on_call``), JSON-serialisable: ``{"name": "generate_image", "args": {"kind", "count"},
  "saved": [{"token", "prompt", "category", "tags"}, ...]}``, each save appended to its call.
* **The scorer.** ``scorers.image_tool_score(structured, expect, *, tool_calls,
  current_deck_spec=None) -> (bool, str)`` for a case whose ``expect`` has ``image_tool``:
  ``{"called": bool, "count": int, "kinds": [...], "slide": int}`` (``slide`` only for an exact
  ask). It checks the call count (exactly one when ``called``, none otherwise), the count and
  kind, ``expect["intent"]`` when given, and, after production's reference reconciliation, that a
  returned token is in slide ``slide``'s ``content_brief`` and on no other slide (exact ask) or
  that nothing references a returned token (otherwise); ``message`` never carries a reference or
  a returned token, and no invented reference survives. Needles: ``called``, ``count``,
  ``kind``, ``intent``, ``content_brief``, ``message``, ``invented``.
* **The wiring.** ``mlflow_run.build_scorers(agent_key, *, judge_endpoint, image_tool=False)``
  adds an ``image_tool`` scorer for the architect only when asked; ``run_sweep`` asks when the
  config binds the tool or a swept case has an ``image_tool`` expectation (a case without one is
  scored as "no call"), logs ``image_tool_pass_rate`` and, only then, the tags ``image_tool`` and
  ``case_set``. A named case set (``run_sweep(..., case_set=NAME)``, the CLI's ``--case-set``)
  is ``evals/packs/<agent>/cases_<NAME>/`` (``case.case_set_dir``); its rows carry
  ``inputs["case_set"]``; train rows are unchanged. ``judge.calibrate(..., root=None)``.
  The CLI prints ``<agent>: run_id=X pass_rate=P image_tool_pass_rate=Q`` for an image-tool
  config or a case set; every other train line is unchanged.
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import hashlib
import json
import re
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from mlflow.entities import Feedback

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case, config, mlflow_run, runner, scorers
from evals.harness import judge as judge_mod
from evals.harness.runner import Runner, RunResult
from src.services.agent_runtime import DatabricksModelAdapter
from src.services.agent_tools.image_generation_tool import (
    BUDGET_SECONDS,
    IMAGE_TOOL_DESCRIPTION,
    IMAGE_TOOL_NAME,
    KIND_TO_PRESET,
    MAX_CALLS_PER_TURN,
    ImageGenerationAgentTool,
    ImageGenerationArgs,
)
from src.services.image_generation import PRESETS
from tests.fixtures.deterministic_model_adapter import fake_output
from tests.fixtures.tool_call_doubles import replying, tool_call_reply

AGENT = "architect"
JUDGE_EP = "stub-judge-endpoint"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
REF_RE = re.compile(r"\{\{image:([A-Za-z0-9_-]+)\}\}")
IMAGE_CONFIG = case.EVALS_DIR / "configs" / "architect" / "image-tool.yaml"


def _tok(n: int) -> str:
    """A token shaped like ``secrets.token_urlsafe(32)``: 43 url-safe characters."""
    return base64.urlsafe_b64encode(hashlib.sha256(f"tok-{n}".encode()).digest()).decode()[:43]


def _image_config(**extra) -> config.AgentEvalConfig:
    base = config.v1_baseline(AGENT)
    return dataclasses.replace(base, name="image-tool", **{"image_tool": True, **extra})


def _payload() -> dict:
    return copy.deepcopy(case.load_case(AGENT, "edit_request").payload)


def _run_tool(tool, args: dict, *, remaining_seconds: float = 240.0) -> str:
    return tool.run(tool.args_schema.model_validate(args), remaining_seconds=remaining_seconds)


class _CapturingAdapter:
    """The runtime's model seam: records the toolset each call is handed and, when scripted, runs
    the image tool as the loop does before answering ``answer`` (a discuss by default)."""

    def __init__(self, *, calls=(), answer: dict | None = None):
        self.calls = [dict(c) for c in calls]
        self.answer = answer
        self.tools_seen: list[tuple] = []
        self.toolsets: list[Any] = []
        self.results: list[str] = []
        self._lock = threading.Lock()

    def invoke(self, *, agent_key, configuration, schema, prompt):
        with self._lock:
            self.tools_seen.append(())
        return schema.model_validate(self.answer or fake_output(agent_key))

    def invoke_with_tools(self, *, agent_key, configuration, schema, prompt, toolset):
        with self._lock:
            self.tools_seen.append(tuple(toolset.tools))
            self.toolsets.append(toolset)
        by_name = {t.name: t for t in toolset.tools}
        for args in self.calls:
            self.results.append(_run_tool(by_name[IMAGE_TOOL_NAME], args))
        return schema.model_validate(self.answer or fake_output(agent_key))


def _run(cfg, adapter, payload=None):
    return Runner(model_adapter=adapter, max_infra_retries=0).run(
        cfg, _payload() if payload is None else payload, design_system_active=True)


def _tokens(result) -> list[str]:
    return [s["token"] for c in result.tool_calls for s in c["saved"]]


# =========================================================================== config: the opt-in

def test_the_opt_in_defaults_off_and_changes_no_definition(tmp_path):
    assert config.v1_baseline(AGENT).image_tool is False
    p = tmp_path / "c.yaml"
    p.write_text("agent_key: architect\nname: x\nimage_tool: true\n")
    cfg = config.load_config(p)
    assert cfg.image_tool is True
    # No prompt or model change: the guidance lives in the tool's description alone.
    assert cfg.content == config.v1_baseline(AGENT).content
    assert cfg.content_hash == config.v1_baseline(AGENT).content_hash
    p.write_text("agent_key: architect\nname: x\n")
    assert config.load_config(p).image_tool is False


def test_the_opt_in_is_the_architect_s_only(tmp_path):
    assert config.IMAGE_TOOL_ROLES == ("architect",)
    p = tmp_path / "c.yaml"
    p.write_text("agent_key: builder\nname: x\nimage_tool: true\n")
    with pytest.raises(config.ConfigError) as e:
        config.load_config(p)
    assert "image_tool" in str(e.value)


@pytest.mark.parametrize("value", ["yes-please", "1", "[true]"])
def test_the_opt_in_must_be_a_boolean(tmp_path, value):
    p = tmp_path / "c.yaml"
    p.write_text(f"agent_key: architect\nname: x\nimage_tool: {value}\n")
    with pytest.raises(config.ConfigError) as e:
        config.load_config(p)
    assert "image_tool" in str(e.value)


def test_the_committed_image_tool_config():
    cfg = config.load_config(IMAGE_CONFIG)
    assert cfg.agent_key == AGENT and cfg.image_tool is True
    assert cfg.content_hash == config.v1_baseline(AGENT).content_hash


# =========================================================================== runner: the binding

def test_an_opted_in_architect_run_binds_production_s_tool_on_its_budget():
    adapter = _CapturingAdapter()
    result = _run(_image_config(), adapter)
    assert result.status == "completed", result.error_detail
    (tools,) = adapter.tools_seen
    (tool,) = tools
    assert type(tool) is ImageGenerationAgentTool
    assert tool.name == IMAGE_TOOL_NAME == "generate_image"
    assert tool.description == IMAGE_TOOL_DESCRIPTION
    assert tool.args_schema is ImageGenerationArgs
    (toolset,) = adapter.toolsets
    assert toolset.max_calls == MAX_CALLS_PER_TURN == 2
    assert toolset.budget_seconds == pytest.approx(BUDGET_SECONDS)
    assert result.tool_calls == ()  # bound, never called


@pytest.mark.parametrize("cfg_body", [None, "", "image_tool: false\n"],
                         ids=["v1-baseline", "yaml-without-key", "yaml-false"])
def test_an_architect_run_that_does_not_opt_in_binds_nothing(tmp_path, cfg_body):
    if cfg_body is None:
        cfg = config.v1_baseline(AGENT)
    else:
        p = tmp_path / "c.yaml"
        p.write_text("agent_key: architect\nname: x\n" + cfg_body)
        cfg = config.load_config(p)
    adapter = _CapturingAdapter()
    result = _run(cfg, adapter)
    assert result.status == "completed", result.error_detail
    assert adapter.tools_seen == [()]
    assert result.tool_calls == ()


def test_a_run_that_does_not_opt_in_still_reaches_a_four_keyword_adapter():
    class _FourKeywords:
        def invoke(self, *, agent_key, configuration, schema, prompt):
            return schema.model_validate(fake_output(agent_key))

    result = _run(config.v1_baseline(AGENT), _FourKeywords())
    assert result.status == "completed", result.error_detail
    assert result.tool_calls == ()


def test_the_opt_in_changes_no_prompt():
    plain = _run(config.v1_baseline(AGENT), _CapturingAdapter())
    bound = _run(_image_config(), _CapturingAdapter())
    assert plain.prompt and plain.prompt == bound.prompt
    assert "generate_image" not in plain.prompt


def test_a_run_that_does_not_opt_in_is_unchanged_field_for_field():
    """Two non-opted runs of one payload agree on every field but the clock, and carry no
    record: the binding adds nothing to a run that does not ask for it."""
    first = _run(config.v1_baseline(AGENT), _CapturingAdapter())
    second = _run(dataclasses.replace(config.v1_baseline(AGENT), image_tool=False),
                  _CapturingAdapter())
    a, b = dataclasses.asdict(first), dataclasses.asdict(second)
    for key in ("latency_ms",):
        a.pop(key), b.pop(key)
    assert a == b
    assert first.tool_calls == ()


@pytest.mark.parametrize("kind", sorted(KIND_TO_PRESET))
def test_the_fake_makes_a_small_valid_image_of_the_preset_s_format(kind):
    adapter = _CapturingAdapter(calls=[{"prompt": "a shield", "kind": kind, "count": 1}])
    result = _run(_image_config(), adapter)
    assert result.status == "completed", result.error_detail
    (reply,) = adapter.results
    preset = PRESETS[KIND_TO_PRESET[kind]]
    mime = {"jpeg": "image/jpeg", "png": "image/png", "svg": "image/svg+xml"}[preset.output_format]
    assert mime in reply, reply
    if preset.output_format != "svg":  # the tool read its size back: a decodable raster
        assert re.search(re.escape(mime) + r", \d+x\d+\)", reply), reply
    assert "not generated" not in reply, reply
    ((entry,),) = [result.tool_calls]
    (saved,) = entry["saved"]
    assert saved["category"] == preset.category
    assert saved["tags"] == ["ai_generated", preset.default_model, preset.id, "chat"]


def test_the_fake_never_reaches_the_network_or_the_database(monkeypatch):
    """The image tool's real backends (the image client, the generator, the Library save) and
    the socket layer are all tripwired: an opted-in run that generates 3 images touches none."""
    import src.services.agent_tools.image_generation_tool as tool_mod
    import src.services.image_generation as image_generation

    touched: list[str] = []
    test_thread = threading.current_thread()

    def ours() -> bool:
        """This test's thread or the tool's pool: a thread another test left running in this
        worker (a keep-alive, a logger) is not this run's and keeps its real socket."""
        current = threading.current_thread()
        return current is test_thread or current.name.startswith("chat-image-gen")

    def tripwire(name, original=None):
        def _raise(*args, **kwargs):
            if original is not None and not ours():
                return original(*args, **kwargs)
            touched.append(name)
            raise AssertionError(f"{name} reached")
        return _raise

    monkeypatch.setattr(
        socket.socket, "connect", tripwire("socket.connect", socket.socket.connect))
    monkeypatch.setattr(
        socket, "create_connection",
        tripwire("socket.create_connection", socket.create_connection))
    monkeypatch.setattr(image_generation, "default_client", tripwire("default_client"))
    monkeypatch.setattr(image_generation.ImageGenerator, "generate", tripwire("ImageGenerator"))
    monkeypatch.setattr(tool_mod, "get_db_session", tripwire("get_db_session"))
    monkeypatch.setattr(tool_mod, "save_generated_image", tripwire("save_generated_image"))

    adapter = _CapturingAdapter(calls=[{"prompt": "a shield", "kind": "illustration", "count": 3}])
    result = _run(_image_config(), adapter)
    assert result.status == "completed", result.error_detail
    assert touched == []
    tokens = _tokens(result)
    assert len(tokens) == 3 and len(set(tokens)) == 3
    assert all(TOKEN_RE.match(t) for t in tokens), tokens
    for t in tokens:
        assert "{{image:" + t + "}}" in adapter.results[0]


def test_a_run_records_each_image_call_and_its_saves():
    adapter = _CapturingAdapter(calls=[
        {"prompt": "three pictures", "kind": "illustration", "count": 3},
        {"prompt": "one icon", "kind": "vector_icon", "count": 1, "for_slide": 2},
    ])
    result = _run(_image_config(), adapter)
    assert result.status == "completed", result.error_detail
    assert [c["name"] for c in result.tool_calls] == [IMAGE_TOOL_NAME, IMAGE_TOOL_NAME]
    assert [c["args"] for c in result.tool_calls] == [
        {"kind": "illustration", "count": 3}, {"kind": "vector_icon", "count": 1}]
    assert [len(c["saved"]) for c in result.tool_calls] == [3, 1]
    assert [s["prompt"] for s in result.tool_calls[0]["saved"]] == ["three pictures"] * 3
    assert "chat_option" in result.tool_calls[0]["saved"][0]["tags"]
    assert "chat_option" not in result.tool_calls[1]["saved"][0]["tags"]
    assert len(set(_tokens(result))) == 4
    json.dumps(list(result.tool_calls))  # MLflow stores it with the row


def test_each_run_records_only_its_own_calls():
    adapter = _CapturingAdapter(calls=[{"prompt": "p", "kind": "icon", "count": 1}])
    r = Runner(model_adapter=adapter, max_infra_retries=0)
    first = r.run(_image_config(), _payload(), design_system_active=True)
    adapter.calls = []
    second = r.run(_image_config(), _payload(), design_system_active=True)
    assert len(first.tool_calls) == 1
    assert second.tool_calls == ()
    first_tool, second_tool = (tools[0] for tools in adapter.tools_seen)
    assert first_tool is not second_tool


def test_each_attempt_gets_a_fresh_tool_and_record(monkeypatch):
    """An infra retry starts over: a new tool with the whole budget, and a record holding only
    the attempt the result reports."""
    from src.services.agent_runtime import ModelProviderUnavailableError

    monkeypatch.setattr(runner.time, "sleep", lambda s: None)

    class _FlakyOnce(_CapturingAdapter):
        def invoke_with_tools(self, *, agent_key, configuration, schema, prompt, toolset):
            first = not self.toolsets
            out = super().invoke_with_tools(agent_key=agent_key, configuration=configuration,
                                            schema=schema, prompt=prompt, toolset=toolset)
            if first:
                raise ModelProviderUnavailableError("503 endpoint down")
            return out

    adapter = _FlakyOnce(calls=[{"prompt": "p", "kind": "icon", "count": 2}])
    result = Runner(model_adapter=adapter, max_infra_retries=1).run(
        _image_config(), _payload(), design_system_active=True)
    assert result.status == "completed", result.error_detail
    one, two = adapter.toolsets
    assert one is not two and one.tools[0] is not two.tools[0]
    assert len(result.tool_calls) == 1 and len(result.tool_calls[0]["saved"]) == 2
    attempt_two_tokens = set(REF_RE.findall(adapter.results[1]))
    assert set(_tokens(result)) == attempt_two_tokens


def test_concurrent_runs_keep_their_records_apart():
    class _PromptPerRun(_CapturingAdapter):
        def invoke_with_tools(self, *, agent_key, configuration, schema, prompt, toolset):
            mark = re.search(r"QRUN-\d+", prompt).group(0)
            _run_tool(toolset.tools[0], {"prompt": mark, "kind": "icon", "count": 1})
            return schema.model_validate(fake_output(agent_key))

    r = Runner(model_adapter=_PromptPerRun(), max_infra_retries=0)

    def one(i):
        payload = _payload()
        payload["message"] = f"QRUN-{i}"
        return i, r.run(_image_config(), payload, design_system_active=True)

    # At most four images in flight: under the tool's process-wide limit of six.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(12)))
    for i, result in results:
        assert result.status == "completed", result.error_detail
        assert [s["prompt"] for c in result.tool_calls for s in c["saved"]] == [f"QRUN-{i}"], i


# --------------------------------------------------------------------------- the real loop

class _ScriptedChat:
    """A chat-model double behind the real ``DatabricksModelAdapter``: records its binding and
    each round's conversation, and answers from a script of ``reply(schema, messages)``."""

    def __init__(self, script):
        self.script = list(script)
        self.bindings: list[tuple[list, dict]] = []
        self.rounds: list[list] = []

    def bind_tools(self, tools, **kwargs):
        tools = list(tools)
        self.bindings.append((tools, kwargs))
        schema = next(t for t in tools if isinstance(t, type))

        def reply(model_input):
            self.rounds.append(
                list(model_input) if isinstance(model_input, list) else [model_input])
            if not self.script:
                raise AssertionError("the model was called more often than scripted")
            return self.script.pop(0)(schema, self.rounds[-1])

        return replying(reply)


def _image_call(args, call_id="call_img"):
    return lambda _schema, _messages: AIMessage(content="", tool_calls=[
        {"name": IMAGE_TOOL_NAME, "args": dict(args), "id": call_id, "type": "tool_call"}])


def _last_tokens(messages) -> list[str]:
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    return REF_RE.findall(tool_messages[-1].content)


def _place_on_slide_2(schema, messages):
    """Answer an edit that puts the generated icon in slide 2's brief (position 1)."""
    (token,) = _last_tokens(messages)
    deck = _payload()["current_deck_spec"]
    slide = {k: v for k, v in deck["slides"][1].items() if k != "position"}
    slide["content_brief"] += (
        " Place {{image:" + token + "}} as a small shield icon beside the title.")
    return tool_call_reply(schema, {
        "intent": "edit", "message": "I've added a shield icon to slide 2.",
        "operations": [{"op": "update", "position": 1, "slides": [slide]}],
        "target_positions": [1]})


def _chat_runner(chat) -> Runner:
    adapter = DatabricksModelAdapter(
        model_factory=lambda **_kw: chat, client_factory=lambda: object())
    return Runner(model_adapter=adapter, max_infra_retries=0)


def test_a_generated_icon_reaches_slide_2_through_the_production_loop():
    chat = _ScriptedChat([
        _image_call({"prompt": "a shield icon", "kind": "icon", "count": 1, "for_slide": 2}),
        _place_on_slide_2,
    ])
    result = _chat_runner(chat).run(_image_config(), _payload(), design_system_active=True)
    assert result.status == "completed", result.error_detail

    # One binding: the output schema, then production's tool definition, auto choice.
    ((bound, kwargs),) = chat.bindings
    assert kwargs == {"tool_choice": "auto"}
    assert [t["function"]["name"] for t in bound[1:]] == [IMAGE_TOOL_NAME]
    assert bound[1]["function"]["description"] == IMAGE_TOOL_DESCRIPTION
    assert set(bound[1]["function"]["parameters"]["properties"]) == {
        "prompt", "kind", "count", "for_slide"}

    # The tool's answer is spotlighted facts carrying the token the record holds.
    tool_message = [m for m in chat.rounds[1] if isinstance(m, ToolMessage)][0]
    assert tool_message.content.startswith('<untrusted-data source="image_generation">')
    (token,) = _tokens(result)
    assert "{{image:" + token + "}}" in tool_message.content
    brief = result.structured["operations"][0]["slides"][0]["content_brief"]
    assert "{{image:" + token + "}}" in brief

    ok, why = scorers.image_tool_score(
        result.structured, {"intent": "edit", "image_tool": {
            "called": True, "count": 1, "kinds": ["icon", "vector_icon"], "slide": 2}},
        tool_calls=result.tool_calls, current_deck_spec=_payload()["current_deck_spec"])
    assert ok, why


def test_the_loop_refuses_a_third_image_call():
    """Production's budget: two calls per turn; the loop answers a third with its budget text and
    the tool never starts it."""
    def answer(schema, _messages):
        return tool_call_reply(schema, {"intent": "discuss", "message": "Pick one."})

    chat = _ScriptedChat([
        _image_call({"prompt": "a", "kind": "illustration", "count": 3}, "c1"),
        _image_call({"prompt": "b", "kind": "illustration", "count": 3}, "c2"),
        _image_call({"prompt": "c", "kind": "illustration", "count": 3}, "c3"),
        answer,
    ])
    result = _chat_runner(chat).run(_image_config(), _payload(), design_system_active=True)
    assert result.status == "completed", result.error_detail
    assert [len(c["saved"]) for c in result.tool_calls] == [3, 3]
    third = [m for m in chat.rounds[3] if isinstance(m, ToolMessage)][-1]
    assert "Tool budget exhausted" in third.content


# =========================================================================== the scorer

DECK = {
    "title": "Passkeys", "audience": "Staff", "purpose": "Switch to passkeys",
    "argument": "Passkeys cannot be phished", "call_to_action": "Set one up",
    "narrative_arc": ["Problem", "Why passkeys", "Ask"],
    "design_contract": {"design_system_id": 3, "template_id": 5},
    "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
    "slides": [
        {"position": i, "purpose": f"Purpose {i}", "content_brief": f"Brief {i}.",
         "assumes": "a", "hands_off": "h", "data_references": []}
        for i in range(3)
    ],
}
OPTIONS = {"intent": "discuss",
           "image_tool": {"called": True, "count": 3, "kinds": ["illustration"]}}
EXACT = {"intent": "edit", "positions": [1],
         "image_tool": {"called": True, "count": 1, "kinds": ["icon", "vector_icon"], "slide": 2}}
NO_CALL = {"intent": "build", "image_tool": {"called": False}}


def _record(kind="illustration", count=3, tokens=None, *, calls=1):
    out = []
    for c in range(calls):
        toks = tokens if tokens is not None else [_tok(10 * c + i) for i in range(count)]
        out.append({"name": IMAGE_TOOL_NAME, "args": {"kind": kind, "count": count},
                    "saved": [{"token": t, "prompt": "p", "category": "content",
                               "tags": ["ai_generated"]} for t in toks]})
    return out


def _discuss(message="Here are three options. Which one would you like?", **extra):
    return {"intent": "discuss", "message": message, "deck_spec": None, "data_request": None,
            "target_positions": [], "proposed_design_contract": None, **extra}


def _slide(position, brief=None):
    s = {k: v for k, v in DECK["slides"][position].items() if k != "position"}
    if brief is not None:
        s["content_brief"] = brief
    return s


def _update(position, brief, message="I've added the icon to slide 2."):
    return {"intent": "edit", "message": message, "target_positions": [position],
            "operations": [{"op": "update", "position": position,
                            "slides": [_slide(position, brief)]}]}


def _ref(token):
    return "{{image:" + token + "}}"


def _score(structured, expect, tool_calls=(), deck=DECK):
    return scorers.image_tool_score(structured, expect, tool_calls=tool_calls,
                                    current_deck_spec=deck)


def test_the_scorer_names_production_s_tool():
    assert scorers.IMAGE_TOOL == IMAGE_TOOL_NAME


# --------------------------------------------------------------------------- open-ended asks

def test_options_pass_one_call_of_three_discussed_and_unplaced():
    ok, why = _score(_discuss(), OPTIONS, _record())
    assert ok, why
    assert "discuss" in why


def test_options_accept_the_record_as_mlflow_stores_it():
    ok, why = _score(_discuss(), OPTIONS, json.loads(json.dumps(_record())))
    assert ok, why


@pytest.mark.parametrize("record,needle", [
    ((), "called"),
    (_record(calls=2), "called"),
    (_record(count=1), "count"),
    (_record(kind="icon"), "kind"),
], ids=["no-call", "two-calls", "count-1", "wrong-kind"])
def test_options_fail_on_the_call(record, needle):
    ok, why = _score(_discuss(), OPTIONS, record)
    assert not ok, why
    assert needle in why.lower(), why


def test_options_ignore_another_tool_s_calls():
    other = [{"name": "search_brand_assets", "args": {"query": None, "kind": "icon"}}]
    ok, why = _score(_discuss(), OPTIONS, other)
    assert not ok and "called" in why.lower(), why
    ok, why = _score(_discuss(), OPTIONS, other + _record())
    assert ok, why


def test_options_fail_on_the_intent():
    tokens = [_tok(i) for i in range(3)]
    placed = _update(1, "Brief 1. Use " + _ref(tokens[0]) + " beside the title.")
    ok, why = _score(placed, OPTIONS, _record(tokens=tokens))
    assert not ok, why
    assert "intent" in why.lower(), why


@pytest.mark.parametrize("where", ["message-ref", "message-bare", "deck_spec"])
def test_options_fail_when_anything_references_a_generated_image(where):
    tokens = [_tok(i) for i in range(3)]
    if where == "message-ref":
        out = _discuss("Option 1 is " + _ref(tokens[0]) + ". Which one?")
    elif where == "message-bare":
        out = _discuss(f"Option 1 is {tokens[0]}. Which one?")
    else:
        deck = copy.deepcopy(DECK)
        deck["slides"][1]["content_brief"] += " " + _ref(tokens[1])
        out = _discuss(deck_spec=deck)
    ok, why = _score(out, OPTIONS, _record(tokens=tokens))
    assert not ok, why
    needle = "message" if where.startswith("message") else "referenc"
    assert needle in why.lower(), why


# --------------------------------------------------------------------------- exact asks

def test_an_exact_ask_passes_one_image_placed_in_the_named_slide_s_brief():
    (token,) = [_tok(1)]
    out = _update(1, "Brief 1. Place " + _ref(token) + " as a small icon beside the title.")
    ok, why = _score(out, EXACT, _record(kind="icon", count=1, tokens=[token]))
    assert ok, why
    assert "slide 2" in why


def test_an_exact_ask_passes_as_a_full_deck_spec_edit():
    token = _tok(1)
    deck = copy.deepcopy(DECK)
    deck["slides"][1]["content_brief"] = "Brief 1. Place " + _ref(token) + " top right, 64px."
    out = {"intent": "edit", "message": "Done.", "target_positions": [1], "deck_spec": deck}
    ok, why = _score(out, EXACT, _record(kind="vector_icon", count=1, tokens=[token]))
    assert ok, why


def test_an_exact_ask_accepts_a_tail_production_corrects():
    """Production reconciles the answer's references against the turn's tokens: a mistyped
    tail sharing the first 12 characters is corrected, so the image still lands."""
    token = _tok(1)
    typo = token[:12] + ("x" if token[12] != "x" else "y") + token[13:]
    out = _update(1, "Brief 1. Place " + _ref(typo) + " beside the title.")
    ok, why = _score(out, EXACT, _record(kind="icon", count=1, tokens=[token]))
    assert ok, why
    assert "correct" in why.lower(), why


@pytest.mark.parametrize("variant,needle", [
    ("not-placed", "content_brief"),
    ("wrong-slide", "content_brief"),
    ("also-another-slide", "slide 3"),
    ("in-message", "message"),
    ("in-look-only", "content_brief"),
    ("invented-extra", "invented"),
    ("discuss", "intent"),
    ("refused", "production would refuse"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_an_exact_ask_fails_on_placement(variant, needle):
    token = _tok(1)
    rec = _record(kind="icon", count=1, tokens=[token])
    if variant == "not-placed":
        out = _update(1, "Brief 1. Add a shield icon beside the title.")
    elif variant == "wrong-slide":
        out = _update(2, "Brief 2. Place " + _ref(token) + " beside the title.")
    elif variant == "also-another-slide":
        out = _update(1, "Brief 1. Place " + _ref(token) + ".")
        out["operations"].append({"op": "update", "position": 2,
                                  "slides": [_slide(2, "Brief 2. Repeat " + _ref(token) + ".")]})
    elif variant == "in-message":
        out = _update(1, "Brief 1. Place " + _ref(token) + ".",
                      message="Added " + _ref(token) + " to slide 2.")
    elif variant == "in-look-only":
        out = _update(1, "Brief 1. Add a shield icon.")
        out["operations"][0]["slides"][0]["look"] = "Icon " + _ref(token) + " top right"
    elif variant == "invented-extra":
        out = _update(1, "Brief 1. Place " + _ref(token) + " and " + _ref("madeUpToken") + ".")
    elif variant == "discuss":
        out = _discuss()
    else:
        out = _update(1, "Brief 1. Place " + _ref(token) + ".")
        out["operations"][0]["position"] = 7  # no such slide
    ok, why = _score(out, EXACT, rec)
    assert not ok, why
    assert needle in why.lower(), why


@pytest.mark.parametrize("record,needle", [
    (_record(kind="icon", count=3), "count"),
    (_record(kind="illustration", count=1), "kind"),
    ((), "called"),
], ids=["three", "wrong-kind", "no-call"])
def test_an_exact_ask_fails_on_the_call(record, needle):
    tokens = [s["token"] for c in record for s in c["saved"]] or [_tok(1)]
    out = _update(1, "Brief 1. Place " + _ref(tokens[0]) + ".")
    ok, why = _score(out, EXACT, record)
    assert not ok, why
    assert needle in why.lower(), why


# --------------------------------------------------------------------------- no image ask

def test_no_image_ask_passes_without_a_call():
    out = {"intent": "build", "message": "Here is the deck.", "deck_spec": DECK}
    ok, why = _score(out, NO_CALL, ())
    assert ok, why
    assert "no generate_image call" in why


def test_no_image_ask_fails_on_any_call():
    out = {"intent": "build", "message": "Here is the deck.", "deck_spec": DECK}
    ok, why = _score(out, NO_CALL, _record())
    assert not ok, why
    assert "called" in why.lower(), why


def test_no_image_ask_fails_on_an_invented_reference():
    deck = copy.deepcopy(DECK)
    deck["slides"][0]["content_brief"] += " Use {{image:inventedRef123}} as the hero."
    out = {"intent": "build", "message": "Here is the deck.", "deck_spec": deck}
    ok, why = _score(out, NO_CALL, ())
    assert not ok, why
    assert "invented" in why.lower(), why


def test_a_reference_the_current_deck_already_carries_is_not_invented():
    deck = copy.deepcopy(DECK)
    deck["slides"][0]["content_brief"] += " Hero {{image:userUploaded01}}."
    out = {"intent": "edit", "message": "Trimmed.", "target_positions": [0], "deck_spec": deck}
    ok, why = _score(out, {"intent": "edit", "image_tool": {"called": False}}, (), deck=deck)
    assert ok, why


def test_no_output_fails():
    ok, why = _score(None, NO_CALL, ())
    assert not ok and "no architect output" in why.lower(), why


# =========================================================================== MLflow wiring

def _patch_judge(monkeypatch, verdict="pass"):
    monkeypatch.setattr(judge_mod, "build_judge",
                        lambda *a, **k: (lambda **kw: Feedback(value=verdict, rationale="stub")))


def _image_scorer(**kw):
    return {s.name: s for s in mlflow_run.build_scorers(AGENT, judge_endpoint=JUDGE_EP, **kw)}


def test_the_image_tool_scorer_is_added_only_when_asked(monkeypatch):
    _patch_judge(monkeypatch)
    assert set(_image_scorer()) == {"contract", "expected_category", "judge"}
    assert set(_image_scorer(image_tool=True)) == {
        "contract", "expected_category", "image_tool", "judge"}
    for role in ("builder", "data_analyst", "fix_reviewer"):
        names = {s.name for s in mlflow_run.build_scorers(role, judge_endpoint=JUDGE_EP,
                                                          image_tool=True)}
        assert "image_tool" not in names, role


def _outputs(structured, tool_calls=(), infra=False):
    return {"structured": structured, "raw": None, "render": None, "latency_ms": 1.0,
            "input_tokens": None, "output_tokens": None,
            "status": "model_error" if infra else "completed", "infra_error": infra,
            "error_detail": None, "tool_calls": list(tool_calls)}


def test_the_image_tool_scorer_scores_the_case_s_expectation(monkeypatch):
    _patch_judge(monkeypatch)
    s = _image_scorer(image_tool=True)["image_tool"]
    inputs = {"agent_key": AGENT, "case_id": "x", "repeat": 0}
    exp = {"expect": OPTIONS, "reference": {}, "design_system_active": True,
           "current_deck_spec": DECK}
    passing = s(inputs=inputs, outputs=_outputs(_discuss(), _record()), expectations=exp)
    assert passing.value == "pass"
    assert s(inputs=inputs, outputs=_outputs(_discuss()), expectations=exp).value == "fail"
    assert s(inputs=inputs, outputs=_outputs(None, infra=True), expectations=exp).value == "skip"


def test_a_case_without_an_expectation_is_scored_as_no_call(monkeypatch):
    _patch_judge(monkeypatch)
    s = _image_scorer(image_tool=True)["image_tool"]
    inputs = {"agent_key": AGENT, "case_id": "x", "repeat": 0}
    exp = {"expect": {"intent": "discuss"}, "reference": {}, "design_system_active": True}
    assert s(inputs=inputs, outputs=_outputs(_discuss()), expectations=exp).value == "pass"
    fb = s(inputs=inputs, outputs=_outputs(_discuss(), _record()), expectations=exp)
    assert fb.value == "fail" and "called" in fb.rationale.lower()


def test_build_dataset_rows_carry_a_case_set_only_when_given():
    c = case.Case("a", AGENT, "positive", True, "", payload={"current_deck_spec": None},
                  reference={}, expect={"intent": "discuss"})
    (plain,) = mlflow_run.build_dataset([c], repeats=1)
    assert plain["inputs"] == {"agent_key": AGENT, "case_id": "a", "repeat": 0}
    (named,) = mlflow_run.build_dataset([c], repeats=1, case_set="image_tool")
    assert named["inputs"] == {**plain["inputs"], "case_set": "image_tool"}


# --------------------------------------------------------------------------- case sets

def test_a_case_set_is_a_named_directory_under_the_pack():
    assert case.case_set_dir(AGENT, "image_tool") == case.PACKS_DIR / AGENT / "cases_image_tool"


@pytest.mark.parametrize("bad", ["", "heldout", "../cases", "Image", "a/b", "image-tool"])
def test_a_case_set_name_is_checked(bad):
    with pytest.raises(ValueError):
        case.case_set_dir(AGENT, bad)


def test_calibrate_reads_a_case_set_s_cases_and_calibration(tmp_path, monkeypatch):
    root = tmp_path / "cases_x"
    d = root / "only"
    d.mkdir(parents=True)
    (d / "case.yaml").write_text("kind: positive\nfault: ''\nexpect:\n  intent: discuss\n")
    (d / "payload.json").write_text(json.dumps({"message": "m", "current_deck_spec": None}))
    ref = {"intent": "discuss", "message": "REF"}
    (d / "reference.json").write_text(json.dumps(ref))
    (d / "calibration.json").write_text(json.dumps({"should_fail": {"intent": "build"}}))
    monkeypatch.setattr(judge_mod, "build_judge", lambda *a, **k: (
        lambda **kw: Feedback(value="pass" if kw["outputs"] == ref else "fail", rationale="s")))
    (row,) = judge_mod.calibrate(AGENT, model=JUDGE_EP, root=root)
    assert row["case_id"] == "only" and row["trusted"] is True, row


# --------------------------------------------------------------------------- sweeps

@pytest.fixture
def tracking(tmp_path, monkeypatch):
    import mlflow

    prev = mlflow.get_tracking_uri()
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    yield uri
    mlflow.end_run()
    mlflow.set_tracking_uri(prev)


def _tiny_case_set(tmp_path, monkeypatch) -> str:
    """A one-case set under a tmp pack: an options ask on DECK."""
    payload = {**_payload(), "current_deck_spec": DECK, "message": "Make me a picture"}
    monkeypatch.setattr(case, "PACKS_DIR", tmp_path / "packs")
    d = case.case_set_dir(AGENT, "tiny") / "opts"
    d.mkdir(parents=True)
    (d / "case.yaml").write_text(json.dumps({
        "kind": "positive", "fault": "", "design_system_active": True, "expect": OPTIONS}))
    (d / "payload.json").write_text(json.dumps(payload))
    (d / "reference.json").write_text(json.dumps(_discuss()))
    (d / "calibration.json").write_text(json.dumps({"should_fail": _discuss()}))
    return "tiny"


def test_a_case_set_sweep_binds_scores_and_reports_the_image_tool(tmp_path, monkeypatch, tracking):
    import mlflow

    name = _tiny_case_set(tmp_path, monkeypatch)
    _patch_judge(monkeypatch)
    adapter = _CapturingAdapter(calls=[{"prompt": "p", "kind": "illustration", "count": 3}],
                                answer=_discuss())
    run_id = mlflow_run.run_sweep(
        _image_config(), agent_key=AGENT, repeats=2, max_workers=2, judge_endpoint=JUDGE_EP,
        runner=Runner(model_adapter=adapter, max_infra_retries=0), tracking_uri=tracking,
        case_set=name)
    mlflow.set_tracking_uri(tracking)
    run = mlflow.get_run(run_id)
    assert run.data.metrics["image_tool_pass_rate"] == pytest.approx(1.0)
    assert run.data.metrics["pass_rate"] == pytest.approx(1.0)
    assert run.data.tags["image_tool"] == "true"
    assert run.data.tags["case_set"] == name
    assert run.data.tags["cases_digest"] == mlflow_run.cases_digest(
        AGENT, root=case.case_set_dir(AGENT, name))
    assert len(adapter.toolsets) == 2


def test_a_case_set_sweep_without_the_tool_fails_the_calls_it_expects(tmp_path, monkeypatch,
                                                                      tracking):
    import mlflow

    name = _tiny_case_set(tmp_path, monkeypatch)
    _patch_judge(monkeypatch)
    adapter = _CapturingAdapter(answer=_discuss())
    run_id = mlflow_run.run_sweep(
        config.v1_baseline(AGENT), agent_key=AGENT, repeats=1, max_workers=1,
        judge_endpoint=JUDGE_EP, runner=Runner(model_adapter=adapter, max_infra_retries=0),
        tracking_uri=tracking, case_set=name)
    mlflow.set_tracking_uri(tracking)
    run = mlflow.get_run(run_id)
    assert adapter.tools_seen == [()]
    assert run.data.metrics["image_tool_pass_rate"] == pytest.approx(0.0)
    assert "image_tool" not in run.data.tags
    assert run.data.tags["case_set"] == name


def test_a_case_set_has_no_held_out_split(tmp_path, monkeypatch, tracking):
    name = _tiny_case_set(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        mlflow_run.run_sweep(_image_config(), agent_key=AGENT, repeats=1, max_workers=1,
                             judge_endpoint=JUDGE_EP, tracking_uri=tracking, split="heldout",
                             case_set=name, runner=Runner(model_adapter=_CapturingAdapter()))


def test_a_default_sweep_logs_no_image_tool_tag_or_metric(monkeypatch, tracking):
    import mlflow

    c = case.load_case(AGENT, "discuss")
    monkeypatch.setattr(mlflow_run, "load_cases", lambda agent_key: [c])
    monkeypatch.setattr(mlflow_run, "load_case", lambda agent_key, case_id: c)
    _patch_judge(monkeypatch)
    adapter = _CapturingAdapter()
    run_id = mlflow_run.run_sweep(
        config.v1_baseline(AGENT), agent_key=AGENT, repeats=1, max_workers=1,
        judge_endpoint=JUDGE_EP, runner=Runner(model_adapter=adapter, max_infra_retries=0),
        tracking_uri=tracking)
    mlflow.set_tracking_uri(tracking)
    run = mlflow.get_run(run_id)
    assert adapter.tools_seen == [()]
    assert "image_tool_pass_rate" not in run.data.metrics
    assert not {"image_tool", "case_set"} & set(run.data.tags)


# =========================================================================== the CLI

@pytest.fixture
def cli_env(tracking, monkeypatch):
    import evals.run_eval as cli

    monkeypatch.setattr(cli, "apply_profile", lambda profile: "https://h")
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: True)
    monkeypatch.setattr(mlflow_run, "default_tracking_uri", lambda: tracking)
    return cli


class _FakeSweep:
    """Stands in for run_sweep: a REAL MLflow run with the metrics the CLI reads back."""

    def __init__(self, metrics):
        self.metrics = metrics
        self.calls = []
        self.run_ids = []

    def __call__(self, cfg, **kw):
        from mlflow.tracking import MlflowClient

        self.calls.append((cfg, kw))
        client = MlflowClient(tracking_uri=kw["tracking_uri"])
        exp = client.get_experiment_by_name("tellr-agent-eval")
        exp_id = exp.experiment_id if exp else client.create_experiment("tellr-agent-eval")
        rid = client.create_run(exp_id).info.run_id
        for k, v in self.metrics.items():
            client.log_metric(rid, k, v)
        client.set_terminated(rid)
        self.run_ids.append(rid)
        return rid


METRICS = {"pass_rate": 0.75, "image_tool_pass_rate": 0.875, "pass_rate/opts": 1.0}


def test_cli_case_set_reaches_the_sweep_and_prints_the_image_tool_pass_rate(cli_env, monkeypatch,
                                                                           capsys):
    sweep = _FakeSweep(METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli_env.main(["--agent", AGENT, "--config", str(IMAGE_CONFIG), "--case-set", "image_tool"])
    ((cfg, kw),) = sweep.calls
    assert cfg.image_tool is True
    assert kw["case_set"] == "image_tool"
    assert capsys.readouterr().out.strip().splitlines() == [
        f"{AGENT}: run_id={sweep.run_ids[0]} pass_rate=0.750 image_tool_pass_rate=0.875"]


def test_cli_image_tool_config_on_train_prints_the_image_tool_pass_rate(cli_env, monkeypatch,
                                                                       capsys):
    sweep = _FakeSweep({"pass_rate": 0.5})
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli_env.main(["--agent", AGENT, "--config", str(IMAGE_CONFIG)])
    ((_, kw),) = sweep.calls
    assert kw.get("case_set") is None
    assert capsys.readouterr().out.strip().splitlines() == [
        f"{AGENT}: run_id={sweep.run_ids[0]} pass_rate=0.500 image_tool_pass_rate=n/a"]


def test_cli_default_train_line_is_unchanged(cli_env, monkeypatch, capsys):
    sweep = _FakeSweep(METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli_env.main(["--agent", AGENT])
    ((_, kw),) = sweep.calls
    assert kw.get("case_set") is None
    assert capsys.readouterr().out.strip().splitlines() == [f"{AGENT}: run_id={sweep.run_ids[0]}"]


@pytest.mark.parametrize("argv", [
    ["--case-set", "image_tool", "--split", "heldout"],
    ["--case-set", "../cases"],
    ["--case-set", "heldout"],
])
def test_cli_rejects_a_bad_case_set(cli_env, monkeypatch, argv):
    sweep = _FakeSweep(METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    with pytest.raises(SystemExit) as e:
        cli_env.main(["--agent", AGENT, *argv])
    assert e.value.code not in (0, None)
    assert sweep.calls == []


def test_cli_calibrate_honours_the_case_set(cli_env, monkeypatch):
    cal = []
    monkeypatch.setattr(judge_mod, "calibrate", lambda *a, **k: cal.append((a, k)) or [
        {"case_id": "opts", "reference_passed": True, "mutation_failed": True, "trusted": True,
         "reason": ""}])
    cli_env.main(["--agent", AGENT, "--calibrate", "--case-set", "image_tool"])
    ((_, kw),) = cal
    assert kw["root"] == case.case_set_dir(AGENT, "image_tool")
    assert "split" not in kw


def test_cli_calibrate_without_a_case_set_passes_no_root(cli_env, monkeypatch):
    cal = []
    monkeypatch.setattr(judge_mod, "calibrate", lambda *a, **k: cal.append((a, k)) or [])
    cli_env.main(["--agent", AGENT, "--calibrate"])
    ((_, kw),) = cal
    assert "root" not in kw


def test_run_result_record_field_is_unchanged():
    assert RunResult.__dataclass_fields__["tool_calls"].default == ()
