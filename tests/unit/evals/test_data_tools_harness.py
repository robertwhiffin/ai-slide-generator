"""Task 8a (agent-mode MCP and Genie Agents): the offline eval harness learns the data analyst's
data tools. Offline: no model endpoint, no workspace, no network.

Names this file fixes for the implementer:

* **The opt-in.** ``AgentEvalConfig.data_tools: bool = False``, read from the YAML key
  ``data_tools`` (a bool), for the data analyst only, like ``image_tool``. It changes no
  definition content, so the content hash stays the v1 one. An architect config that sets it is
  rejected (``ConfigError``) or binds nothing.
* **The binding.** ``Runner.run`` keeps its signature. A data-analyst run of a config with
  ``data_tools: true`` gets, through ``_RUN_TOOLSET`` / ``_ToolLoopAdapter`` as the brand search
  and the image tool do, a fresh toolset per run holding exactly three production tool classes
  over fake clients:

  - ``GenieOneAgentTool`` named ``genie`` (its description names Genie One);
  - ``GenieAgentTool`` named ``genie_agent_sales``, space ``"Sales"``, user description
    ``"Regional sales by month: revenue, units and orders per region"``;
  - one ``GatewayMcpAgentTool`` named ``you-search``, described as web search.

  The toolset has production's analyst budget for more than Genie One alone (R4:
  ``ANALYST_GATEWAY_MAX_CALLS`` calls, ``ANALYST_GATEWAY_BUDGET_SECONDS`` seconds). Each Genie
  fake answers with a completed ``GenieOneAnswer`` holding ONE small result table, its ``source``
  the tool's (``"Genie One"``, ``"Genie Agent · Sales"``); the web fake answers with canned text.
  Nothing reaches a network or a database. Every other run binds nothing, exactly as before.
* **The record** (``RunResult.tool_calls``), one entry per call a fake answered, in call order,
  JSON-serialisable, shaped as the brand search records: ``{"name": <model tool name>,
  "args": <the call's arguments>}`` (a Genie call's args are ``{"question": ...}``).
* **The scorer.** ``scorers.data_tool_score(outputs, expectations, trace_or_record)``, called
  positionally here as MLflow scorer arguments: ``outputs`` is a row's predict output (it carries
  ``tool_calls``), ``expectations`` is a row's expectations (the case's ``expect`` under
  ``"expect"``), the third argument is the run's record. Without ``expect["first_tool"]`` it does
  not run: it returns ``None`` (or ``(None, why)``). Otherwise ``(ok, why)``: it passes when the
  first recorded call's ``name`` equals ``first_tool`` and, with ``expect["no_sql"]`` true, no
  recorded ``question`` argument matches ``(?i)\\bselect\\b.+\\bfrom\\b``.
* **The wiring.** ``mlflow_run.build_scorers(agent_key, *, judge_endpoint, ...)`` includes a
  ``data_tool`` scorer for the data analyst (and for no other role); it skips a row with an
  infra error or without ``first_tool``. ``run_sweep`` logs ``data_tool_pass_rate`` (none when
  every row skipped). The CLI prints ``data_tool_pass_rate=<rate>`` on the analyst's train line
  beside ``pass_rate``.
* **The case set.** ``evals/packs/data_analyst/cases_data_tools/`` (generator
  ``evals/packs/data_analyst/data_tools.py``, ``generate(out_dir=None)``, ``CASES_DIR``): three
  cases, each ``expect.outcome: success`` and a ``first_tool``.
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import re
import socket
import threading
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from mlflow.entities import Feedback

import src.core.database  # noqa: F401  (break import cycle before src.services.*)
from evals.harness import case, config, mlflow_run, scorers
from evals.harness import judge as judge_mod
from evals.harness.runner import Runner
from src.domain.skill_io import AnalystOutput
from src.services.agent_model_payload import model_payload_for
from src.services.agent_runtime import DatabricksModelAdapter
from src.services.agent_tools.gateway_tool import GatewayMcpAgentTool
from src.services.agent_tools.gateway_toolset import (
    ANALYST_GATEWAY_BUDGET_SECONDS,
    ANALYST_GATEWAY_MAX_CALLS,
)
from src.services.agent_tools.genie_agent import GenieAgentTool
from src.services.agent_tools.genie_one import (
    GENIE_AGENT_SOURCE_PREFIX,
    GENIE_ONE_SOURCE,
    GenieOneAnswer,
)
from src.services.agent_tools.registry import GenieOneAgentTool
from tests.fixtures.deterministic_model_adapter import fake_output
from tests.fixtures.tool_call_doubles import replying, tool_call_reply

ANALYST = "data_analyst"
JUDGE_EP = "stub-judge-endpoint"
TOOL_NAMES = {"genie", "genie_agent_sales", "you-search"}
SALES_DESCRIPTION = "Regional sales by month: revenue, units and orders per region"
FILES = ("calibration.json", "case.yaml", "payload.json", "reference.json")
DATA_TOOLS_CASES = {"fits_genie_agent", "outside_genie_agent", "web_fact"}

BUSINESS_Q = "What was revenue by region last quarter?"
TICKETS_Q = "How many support tickets were opened each month this year?"
WEB_QUERY = "global CRM software market size estimate"
SQL_Q = "SELECT region, SUM(revenue) FROM sales GROUP BY region"

SUCCESS = {"outcome": "success", "synthesis": "EMEA led revenue last quarter.",
           "sources": [GENIE_AGENT_SOURCE_PREFIX + "Sales"]}
NO_TOOL = {"outcome": "no_tool", "reason": "No tool can answer this."}

FITS = {"outcome": "success", "first_tool": "genie_agent_sales", "no_sql": True}
OUTSIDE = {"outcome": "success", "first_tool": "genie"}
WEB = {"outcome": "success", "first_tool": "you-search"}


def _tools_config(tmp_path, body: str = "data_tools: true\n") -> config.AgentEvalConfig:
    """An analyst config loaded from YAML, as the CLI loads one."""
    p = tmp_path / "data-tools.yaml"
    p.write_text("agent_key: data_analyst\nname: data-tools\n" + body)
    return config.load_config(p)


def _payload(request: str = BUSINESS_Q) -> dict:
    p = {"data_request": request, "deck_purpose": "A quarterly sales review"}
    assert model_payload_for(ANALYST, p) == p  # production-shaped
    return p


class _CapturingAdapter:
    """The runtime's model seam: records the toolset each call is handed and, when scripted, runs
    the named tools as the loop does (``tool.run``) before answering ``answer``."""

    def __init__(self, *, calls=(), answer: dict | None = None):
        self.calls = [(name, dict(args)) for name, args in calls]
        self.answer = answer
        self.tools_seen: list[tuple] = []
        self.toolsets: list[Any] = []
        self.replies: list[tuple[str, str]] = []
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
        for name, args in self.calls:
            tool = by_name[name]
            reply = tool.run(tool.args_schema.model_validate(args), remaining_seconds=240.0)
            self.replies.append((name, reply))
        return schema.model_validate(self.answer or fake_output(agent_key))


def _run(cfg, adapter, payload=None):
    return Runner(model_adapter=adapter, max_infra_retries=0).run(
        cfg, _payload() if payload is None else payload, design_system_active=True)


def _call(name: str, **args) -> dict:
    """One record entry, shaped as the brand search records its calls."""
    return {"name": name, "args": args}


def _outputs(record, structured=None, infra: bool = False) -> dict:
    """A row's predict output (``mlflow_run.make_predict_fn``'s keys)."""
    return {"structured": SUCCESS if structured is None else structured, "raw": None,
            "render": None, "latency_ms": 1.0, "input_tokens": None, "output_tokens": None,
            "status": "model_error" if infra else "completed", "infra_error": infra,
            "error_detail": None, "tool_calls": list(record)}


def _expectations(expect: dict) -> dict:
    """A row's expectations (``mlflow_run.build_dataset``'s keys)."""
    return {"expect": expect, "reference": SUCCESS, "design_system_active": True}


def _score(record, expect):
    return scorers.data_tool_score(_outputs(record), _expectations(expect), record)


def _is_skip(result) -> bool:
    return result is None or (isinstance(result, tuple) and result[0] is None)


def _patch_judge(monkeypatch, verdict="pass"):
    monkeypatch.setattr(judge_mod, "build_judge",
                        lambda *a, **k: (lambda **kw: Feedback(value=verdict, rationale="stub")))


# =========================================================================== config: the opt-in

def test_the_data_tools_opt_in_defaults_off_and_changes_no_definition(tmp_path):
    assert config.v1_baseline(ANALYST).data_tools is False
    cfg = _tools_config(tmp_path)
    assert cfg.data_tools is True
    # A harness setting, not definition content: the prompt and model are v1's.
    assert cfg.content == config.v1_baseline(ANALYST).content
    assert cfg.content_hash == config.v1_baseline(ANALYST).content_hash
    assert _tools_config(tmp_path, body="").data_tools is False


@pytest.mark.parametrize("value", ["yes-please", "1", "[true]"])
def test_the_data_tools_opt_in_must_be_a_boolean(tmp_path, value):
    with pytest.raises(config.ConfigError) as e:
        _tools_config(tmp_path, body=f"data_tools: {value}\n")
    assert "data_tools" in str(e.value)
    assert "unknown config key" not in str(e.value)  # a known key, refused for its value


# =========================================================================== runner: the binding

def test_data_tools_binds_the_three_fake_tools_for_the_analyst_only(tmp_path):
    # The analyst: exactly the three production tool classes, bound and not yet called.
    adapter = _CapturingAdapter()
    result = _run(_tools_config(tmp_path), adapter)
    assert result.status == "completed", result.error_detail
    (tools,) = adapter.tools_seen
    by_name = {t.name: t for t in tools}
    assert len(tools) == 3 and set(by_name) == TOOL_NAMES, sorted(by_name)

    genie = by_name["genie"]
    assert type(genie) is GenieOneAgentTool
    assert "Genie One" in genie.description

    sales = by_name["genie_agent_sales"]
    assert type(sales) is GenieAgentTool
    assert sales.space_name == "Sales"
    assert SALES_DESCRIPTION in sales.description
    assert sales.source == GENIE_AGENT_SOURCE_PREFIX + "Sales"

    web = by_name["you-search"]
    assert type(web) is GatewayMcpAgentTool
    assert re.search(r"\bweb\b", web.description, re.I), web.description
    assert re.search(r"\bsearch", web.description, re.I), web.description
    assert result.tool_calls == ()  # bound, never called

    # The architect: an architect config that sets data_tools is rejected, or binds nothing.
    arch_payload = case.load_case("architect", "discuss").payload
    p = tmp_path / "architect.yaml"
    p.write_text("agent_key: architect\nname: x\ndata_tools: true\n")
    candidates = []
    try:
        candidates.append(config.load_config(p))
    except config.ConfigError as e:
        assert "data_tools" in str(e)
    try:
        candidates.append(dataclasses.replace(config.v1_baseline("architect"), data_tools=True))
    except ValueError:  # ConfigError included: rejected when built
        pass
    for arch in candidates:
        arch_adapter = _CapturingAdapter()
        arch_result = _run(arch, arch_adapter, payload=arch_payload)
        assert arch_result.status == "completed", arch_result.error_detail
        assert arch_adapter.tools_seen == [()]
        assert arch_result.tool_calls == ()


@pytest.mark.parametrize("cfg_body", [None, "", "data_tools: false\n"],
                         ids=["v1-baseline", "yaml-without-key", "yaml-false"])
def test_an_analyst_run_that_does_not_opt_in_binds_nothing(tmp_path, cfg_body):
    """The analyst's train cases ``needs_tool`` and ``unsourced_public_stat`` expect ``no_tool``:
    a config without the opt-in must run with no tool bound, exactly as before."""
    cfg = config.v1_baseline(ANALYST) if cfg_body is None else _tools_config(tmp_path, cfg_body)
    adapter = _CapturingAdapter()
    result = _run(cfg, adapter)
    assert result.status == "completed", result.error_detail
    assert adapter.tools_seen == [()]
    assert result.tool_calls == ()


def test_the_data_tools_ride_production_s_analyst_budget(tmp_path):
    """R4: with more than Genie One alone, production's analyst toolset holds
    ``ANALYST_GATEWAY_MAX_CALLS`` calls and ``ANALYST_GATEWAY_BUDGET_SECONDS`` seconds."""
    adapter = _CapturingAdapter()
    _run(_tools_config(tmp_path), adapter)
    (toolset,) = adapter.toolsets
    assert toolset.max_calls == ANALYST_GATEWAY_MAX_CALLS == 6
    assert toolset.budget_seconds == pytest.approx(ANALYST_GATEWAY_BUDGET_SECONDS, abs=1.0)


def test_each_fake_answers_and_records_its_name_and_arguments(tmp_path):
    adapter = _CapturingAdapter(calls=[
        ("genie_agent_sales", {"question": BUSINESS_Q}),
        ("genie", {"question": TICKETS_Q}),
        ("you-search", {"query": WEB_QUERY}),
    ])
    result = _run(_tools_config(tmp_path), adapter)
    assert result.status == "completed", result.error_detail

    # The record: one entry per call, in call order, as the brand search records.
    assert [(c["name"], c["args"]) for c in result.tool_calls] == [
        ("genie_agent_sales", {"question": BUSINESS_Q}),
        ("genie", {"question": TICKETS_Q}),
        ("you-search", {"query": WEB_QUERY}),
    ]
    assert json.loads(json.dumps(list(result.tool_calls))) == list(result.tool_calls)

    # Each Genie fake: a completed GenieOneAnswer with one small result table, its source the
    # tool's, rendered by production into a spotlighted reply.
    (tools,) = adapter.tools_seen
    by_name = {t.name: t for t in tools}
    replies = dict(adapter.replies)
    for name, source, spotlight_source in (
        ("genie", GENIE_ONE_SOURCE, "genie_one"),
        ("genie_agent_sales", GENIE_AGENT_SOURCE_PREFIX + "Sales", "genie_agent"),
    ):
        (answer,) = by_name[name].answers
        assert isinstance(answer, GenieOneAnswer), name
        assert answer.status == "completed", name
        assert answer.source == source, name
        (table,) = answer.query_results
        assert table.columns and all(table.columns), name
        assert 1 <= len(table.rows) <= 20, name
        assert all(len(row) == len(table.columns) for row in table.rows), name
        reply = replies[name]
        assert reply.startswith(f'<untrusted-data source="{spotlight_source}">'), reply
        assert "| " + " | ".join(table.columns) + " |" in reply, reply

    # The web fake: a canned answer, run as a Gateway tool runs (no failure text).
    web_reply = replies["you-search"]
    assert web_reply.startswith("<untrusted-data source="), web_reply
    body = web_reply.split(">", 1)[1].rsplit("</untrusted-data>", 1)[0].strip()
    assert body, web_reply
    for failure in ("could not run", "Tool error", "Not run", "sign in", "does not have access"):
        assert failure not in body, web_reply


def test_the_fakes_never_reach_the_network_or_the_database(tmp_path, monkeypatch):
    """The real clients' entry points and the socket layer are tripwired: an opted-in run that
    calls all three tools touches none of them."""
    import src.services.agent_tools.gateway_mcp as gateway_mcp
    import src.services.agent_tools.gateway_tool as gateway_tool
    import src.services.agent_tools.genie_agent as genie_agent
    import src.services.agent_tools.genie_one as genie_one
    import src.services.agent_tools.mcp_transport as mcp_transport

    touched: list[str] = []
    before = {t.ident for t in threading.enumerate()} - {threading.get_ident()}

    def ours() -> bool:
        """This test's thread, or a thread the run started (a timeout worker): a thread another
        test left running in this worker keeps its real socket."""
        return threading.get_ident() not in before

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
    monkeypatch.setattr(mcp_transport, "build_user_mcp_client", tripwire("mcp client"))
    monkeypatch.setattr(gateway_mcp, "build_user_mcp_client", tripwire("gateway mcp client"))
    monkeypatch.setattr(genie_one, "build_user_mcp_client", tripwire("genie one mcp client"))
    monkeypatch.setattr(genie_agent, "WorkspaceClient", tripwire("WorkspaceClient"))
    monkeypatch.setattr(gateway_tool, "get_db_session", tripwire("get_db_session"))

    adapter = _CapturingAdapter(calls=[
        ("genie_agent_sales", {"question": BUSINESS_Q}),
        ("genie", {"question": TICKETS_Q}),
        ("you-search", {"query": WEB_QUERY}),
    ])
    result = _run(_tools_config(tmp_path), adapter)
    assert result.status == "completed", result.error_detail
    assert touched == []
    assert [c["name"] for c in result.tool_calls] == ["genie_agent_sales", "genie", "you-search"]


def test_each_run_gets_fresh_tools_and_its_own_record(tmp_path):
    cfg = _tools_config(tmp_path)
    adapter = _CapturingAdapter(calls=[("genie", {"question": TICKETS_Q})])
    r = Runner(model_adapter=adapter, max_infra_retries=0)
    first = r.run(cfg, _payload(), design_system_active=True)
    adapter.calls = []
    second = r.run(cfg, _payload(), design_system_active=True)
    assert [c["name"] for c in first.tool_calls] == ["genie"]
    assert second.tool_calls == ()
    one, two = ({t.name: t for t in tools} for tools in adapter.tools_seen)
    assert set(one) == set(two) == TOOL_NAMES
    for name in TOOL_NAMES:
        assert one[name] is not two[name], name
    assert len(one["genie"].answers) == 1
    assert two["genie"].answers == []


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


def _tool_call(name, args, call_id="call_1"):
    return lambda _schema, _messages: AIMessage(content="", tool_calls=[
        {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}])


def test_a_genie_agent_question_is_recorded_and_scored_through_the_production_loop(tmp_path):
    chat = _ScriptedChat([
        _tool_call("genie_agent_sales", {"question": BUSINESS_Q}),
        lambda schema, _messages: tool_call_reply(schema, SUCCESS),
    ])
    adapter = DatabricksModelAdapter(
        model_factory=lambda **_kw: chat, client_factory=lambda: object())
    result = Runner(model_adapter=adapter, max_infra_retries=0).run(
        _tools_config(tmp_path), _payload(), design_system_active=True)
    assert result.status == "completed", result.error_detail
    assert result.structured["outcome"] == "success"

    # One binding: the output schema, then the three tools, each a valid function definition.
    ((bound, kwargs),) = chat.bindings
    assert kwargs == {"tool_choice": "auto"}
    defs = {t["function"]["name"]: t["function"] for t in bound[1:]}
    assert set(defs) == TOOL_NAMES
    assert defs["you-search"]["parameters"].get("type") == "object"
    assert set(defs["genie_agent_sales"]["parameters"]["properties"]) == {"question"}

    # The model read the Genie Agent's table, spotlighted; the record holds its one call.
    tool_message = [m for m in chat.rounds[1] if isinstance(m, ToolMessage)][0]
    assert tool_message.content.startswith('<untrusted-data source="genie_agent">')
    assert "| ---" in tool_message.content
    assert [(c["name"], c["args"]) for c in result.tool_calls] == [
        ("genie_agent_sales", {"question": BUSINESS_Q})]

    outputs = _outputs(result.tool_calls, structured=result.structured)
    ok, why = scorers.data_tool_score(outputs, _expectations(FITS), result.tool_calls)
    assert ok is True, why
    ok, why = scorers.data_tool_score(outputs, _expectations(OUTSIDE), result.tool_calls)
    assert ok is False, why


# =========================================================================== the scorer

@pytest.mark.parametrize("record,expect", [
    ([_call("genie_agent_sales", question=BUSINESS_Q), _call("genie", question=TICKETS_Q)], FITS),
    ([_call("genie", question=TICKETS_Q)], OUTSIDE),
    ([_call("you-search", query=WEB_QUERY)], WEB),
    ([_call("genie_agent_sales", question=BUSINESS_Q), _call("you-search", query=WEB_QUERY),
      _call("genie", question=TICKETS_Q)], FITS),
    ([_call("genie_agent_sales", question="Which regions should we select for the pilot?")],
     FITS),
], ids=["fits", "outside", "web", "later-calls-ignored", "select-without-from"])
def test_data_tool_score_passes_on_the_expected_first_call(record, expect):
    ok, why = _score(record, expect)
    assert ok is True, why
    assert expect["first_tool"] in why, why
    # As MLflow stores the record (JSON) and as RunResult carries it (a tuple).
    ok, why = _score(json.loads(json.dumps(record)), expect)
    assert ok is True, why
    ok, why = _score(tuple(record), expect)
    assert ok is True, why


@pytest.mark.parametrize("record,expect", [
    ([_call("genie", question=BUSINESS_Q), _call("genie_agent_sales", question=BUSINESS_Q)], FITS),
    ([_call("you-search", query=TICKETS_Q)], OUTSIDE),
    ([_call("genie_agent_sales", question=TICKETS_Q)], OUTSIDE),
    ([_call("genie", question=WEB_QUERY)], WEB),
    ([], WEB),
], ids=["genie-before-the-agent", "web-for-genie", "agent-for-genie", "genie-for-web", "no-call"])
def test_data_tool_score_fails_on_a_different_first_call(record, expect):
    ok, why = _score(record, expect)
    assert ok is False, why
    assert expect["first_tool"] in why, why


@pytest.mark.parametrize("record", [
    [_call("genie_agent_sales", question=SQL_Q)],
    [_call("genie_agent_sales", question=BUSINESS_Q),
     _call("genie_agent_sales", question="select region, sum(units) from orders")],
    [_call("genie_agent_sales", question=BUSINESS_Q), _call("genie", question=SQL_Q)],
], ids=["first-call", "later-call-lower-case", "another-tool"])
def test_data_tool_score_fails_on_a_sql_question_when_no_sql(record):
    ok, why = _score(record, FITS)
    assert ok is False, why
    assert "sql" in why.lower(), why
    # The SQL rule holds only with no_sql: true.
    for expect in ({**FITS, "no_sql": False}, {k: v for k, v in FITS.items() if k != "no_sql"}):
        ok, why = _score(record, expect)
        assert ok is True, (expect, why)


@pytest.mark.parametrize("expect", [
    {"outcome": "success"},
    {"outcome": "no_tool"},
    {"outcome": "success", "no_sql": True},
    {},
], ids=["train-success", "train-no-tool", "no-sql-alone", "empty"])
def test_data_tool_score_skips_without_first_tool(expect):
    for record in ([_call("genie", question=SQL_Q)], []):
        result = _score(record, expect)
        assert _is_skip(result), result


# =========================================================================== MLflow wiring

def test_build_scorers_includes_data_tool(monkeypatch):
    _patch_judge(monkeypatch)
    by_name = {s.name: s for s in mlflow_run.build_scorers(ANALYST, judge_endpoint=JUDGE_EP)}
    assert "data_tool" in by_name
    assert {"contract", "expected_category", "judge"} <= set(by_name)
    for role in ("architect", "builder", "fixer", "build_reviewer", "fix_reviewer",
                 "deck_reviewer"):
        names = {s.name for s in mlflow_run.build_scorers(role, judge_endpoint=JUDGE_EP)}
        assert "data_tool" not in names, role

    s = by_name["data_tool"]
    inputs = {"agent_key": ANALYST, "case_id": "x", "repeat": 0}

    def value(record, expect, infra=False):
        return s(inputs=inputs, outputs=_outputs(record, infra=infra),
                 expectations=_expectations(expect)).value

    good = [_call("genie_agent_sales", question=BUSINESS_Q)]
    assert value(good, FITS) == "pass"
    assert value([_call("genie", question=BUSINESS_Q)], FITS) == "fail"
    assert value([_call("genie_agent_sales", question=SQL_Q)], FITS) == "fail"
    assert value(good, {"outcome": "success"}) == "skip"  # a train case
    assert value((), FITS, infra=True) == "skip"


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
    """A one-case analyst set under a tmp pack: a request the Sales Genie Agent fits."""
    monkeypatch.setattr(case, "PACKS_DIR", tmp_path / "packs")
    d = case.case_set_dir(ANALYST, "tiny") / "fits"
    d.mkdir(parents=True)
    (d / "case.yaml").write_text(json.dumps({
        "kind": "positive", "fault": "", "design_system_active": True, "expect": FITS}))
    (d / "payload.json").write_text(json.dumps(_payload()))
    (d / "reference.json").write_text(json.dumps(SUCCESS))
    (d / "calibration.json").write_text(json.dumps({"should_fail": NO_TOOL}))
    return "tiny"


@pytest.mark.parametrize("first,rate", [("genie_agent_sales", 1.0), ("genie", 0.0)])
def test_a_data_tools_case_set_sweep_logs_the_data_tool_pass_rate(tmp_path, monkeypatch, tracking,
                                                                  first, rate):
    import mlflow

    cfg = _tools_config(tmp_path)
    name = _tiny_case_set(tmp_path, monkeypatch)
    _patch_judge(monkeypatch)
    adapter = _CapturingAdapter(calls=[(first, {"question": BUSINESS_Q})], answer=SUCCESS)
    run_id = mlflow_run.run_sweep(
        cfg, agent_key=ANALYST, repeats=2, max_workers=1, judge_endpoint=JUDGE_EP,
        runner=Runner(model_adapter=adapter, max_infra_retries=0), tracking_uri=tracking,
        case_set=name)
    mlflow.set_tracking_uri(tracking)
    metrics = mlflow.get_run(run_id).data.metrics
    assert metrics["data_tool_pass_rate"] == pytest.approx(rate)
    assert metrics["pass_rate"] == pytest.approx(rate)  # the data_tool scorer counts in the row
    assert len(adapter.toolsets) == 2


def test_a_train_analyst_sweep_logs_no_data_tool_pass_rate(monkeypatch, tracking):
    """Every train row skips the data_tool scorer (no first_tool): no metric, unchanged rows."""
    import mlflow

    c = case.load_case(ANALYST, "figures_inline")
    monkeypatch.setattr(mlflow_run, "load_cases", lambda agent_key, **kw: [c])
    monkeypatch.setattr(mlflow_run, "load_case", lambda agent_key, case_id, **kw: c)
    _patch_judge(monkeypatch)
    adapter = _CapturingAdapter()
    run_id = mlflow_run.run_sweep(
        config.v1_baseline(ANALYST), agent_key=ANALYST, repeats=1, max_workers=1,
        judge_endpoint=JUDGE_EP, runner=Runner(model_adapter=adapter, max_infra_retries=0),
        tracking_uri=tracking)
    mlflow.set_tracking_uri(tracking)
    metrics = mlflow.get_run(run_id).data.metrics
    assert adapter.tools_seen == [()]
    assert metrics["pass_rate"] == pytest.approx(1.0)
    assert "data_tool_pass_rate" not in metrics


# --------------------------------------------------------------------------- the CLI

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


def test_cli_prints_the_data_tool_pass_rate_beside_the_other_rates(tmp_path, cli_env, monkeypatch,
                                                                  capsys):
    p = tmp_path / "multi-source-tools.yaml"
    p.write_text("agent_key: data_analyst\nname: multi-source-tools\ndata_tools: true\n")
    sweep = _FakeSweep({"pass_rate": 0.75, "data_tool_pass_rate": 0.875})
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli_env.main(["--agent", ANALYST, "--config", str(p), "--case-set", "data_tools"])
    ((cfg, kw),) = sweep.calls
    assert cfg.data_tools is True
    assert kw["case_set"] == "data_tools"
    (line,) = capsys.readouterr().out.strip().splitlines()
    assert line.startswith(f"{ANALYST}: run_id={sweep.run_ids[0]} pass_rate=0.750"), line
    assert re.search(r"(^| )data_tool_pass_rate=0\.875( |$)", line), line


# =========================================================================== the case set

def _data_tools_root():
    return case.case_set_dir(ANALYST, "data_tools")


def _data_tools_cases() -> dict:
    return {c.case_id: c for c in case.load_cases(ANALYST, root=_data_tools_root())}


def test_every_data_tools_case_expects_success_and_a_first_tool():
    root = _data_tools_root()
    assert root == case.PACKS_DIR / ANALYST / "cases_data_tools"
    cases = _data_tools_cases()
    assert set(cases) == DATA_TOOLS_CASES
    assert {d.name for d in root.iterdir() if d.is_dir()} == DATA_TOOLS_CASES
    for cid, c in cases.items():
        # The usual four files: calibration judges the reference and the should_fail.
        assert sorted(p.name for p in (root / cid).iterdir()) == sorted(FILES), cid
        assert c.agent_key == ANALYST
        assert c.expect["outcome"] == "success", cid
        assert isinstance(c.expect.get("first_tool"), str), cid
        assert model_payload_for(ANALYST, c.payload) == c.payload, cid

    assert cases["fits_genie_agent"].expect["first_tool"] == "genie_agent_sales"
    assert cases["fits_genie_agent"].expect["no_sql"] is True
    assert cases["outside_genie_agent"].expect["first_tool"] == "genie"
    assert cases["web_fact"].expect["first_tool"] == "you-search"

    requests = {cid: c.payload["data_request"] for cid, c in cases.items()}
    assert re.search(r"\brevenue\b", requests["fits_genie_agent"], re.I), requests
    assert re.search(r"\bregion", requests["fits_genie_agent"], re.I), requests
    assert re.search(r"\bsupport\b", requests["outside_genie_agent"], re.I), requests
    assert re.search(r"\btickets?\b", requests["outside_genie_agent"], re.I), requests
    assert re.search(r"\bmarket\b", requests["web_fact"], re.I), requests
    assert re.search(r"\bsize\b", requests["web_fact"], re.I), requests
    # The set lives apart from the analyst's train and held-out cases.
    for split in case.SPLITS:
        ids = {c.case_id for c in case.load_cases(ANALYST, split=split)}
        assert not ids & DATA_TOOLS_CASES, split


def test_the_data_tools_cases_name_the_tools_the_runner_binds(tmp_path):
    """Each case's ``first_tool`` is a tool a data_tools run binds, all three are some case's,
    and each reference passes both deterministic scorers given the call it implies."""
    adapter = _CapturingAdapter()
    _run(_tools_config(tmp_path), adapter)
    (tools,) = adapter.tools_seen
    cases = _data_tools_cases()
    assert set(cases) == DATA_TOOLS_CASES
    assert {c.expect["first_tool"] for c in cases.values()} == {t.name for t in tools}

    for cid, c in cases.items():
        AnalystOutput.model_validate(c.reference)
        ok, why = scorers.expected_category_score(ANALYST, c.reference, c.expect)
        assert ok, (cid, why)
        first = c.expect["first_tool"]
        arg = "query" if first == "you-search" else "question"
        record = [_call(first, **{arg: c.payload["data_request"]})]
        ok, why = scorers.data_tool_score(
            _outputs(record, structured=c.reference),
            {"expect": c.expect, "reference": c.reference,
             "design_system_active": c.design_system_active},
            record)
        assert ok is True, (cid, why)

        bad = json.loads((_data_tools_root() / cid / "calibration.json").read_text())["should_fail"]
        AnalystOutput.model_validate(bad)
        # The analyst judge sees the request and the answer, never the record: the should_fail
        # must read differently from the reference.
        assert bad != c.reference, cid


def _tree(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_data_tools_case_set_is_generated(tmp_path):
    gen = importlib.import_module("evals.packs.data_analyst.data_tools")
    assert gen.CASES_DIR == _data_tools_root()
    committed = _tree(_data_tools_root())
    assert committed
    out = tmp_path / "cases_data_tools"
    gen.generate(out_dir=out)
    assert _tree(out) == committed
    assert _tree(_data_tools_root()) == committed  # writing elsewhere leaves the set untouched
