"""Failing tests for issue #313 Task 2: ``evals/intent_report.py``, a read-only report of the
architect's INTENT accuracy and POSITION accuracy over one eval run.

RED until ``evals/intent_report.py`` exists (collection fails with ModuleNotFoundError).

Why it exists: the harness's ``expected_category`` scorer (``evals/harness/scorers.py``) fails an
architect row when the intent is wrong OR when an edit's ``target_positions`` are wrong, so its pass
rate is not intent accuracy; and MLflow aggregates no "pass"/"fail" values. Plan D9 defines:

* intent accuracy -- got intent == expected intent, over non-infra rows. A row with no output
  (``structured`` not a dict) counts as wrong and is also counted as ``no_output``;
* position accuracy -- over rows whose expected AND got intent are both "edit", the share whose
  ``set(target_positions)`` equals the expected set (order and duplicates ignored).

Names and behaviours this file fixes for the implementer, beyond the plan's interface:

* ``from evals import intent_report``; it exposes ``row_from_trace``, ``summarise``, ``report``, ``main``.
* ``summarise(...)["rows"]`` (and each ``per_case`` entry's ``"rows"``) is an int count.
* ``report(...)`` returns summarise()'s keys for the rows it counted plus ``infra_skipped`` (int).
* ``report(tracking_uri=None)`` resolves ``mlflow_run.default_tracking_uri()`` at CALL time (these tests
  patch that module attribute, so no test can ever open the worktree's real ``mlflow.db``).
* ``report`` reads only the store named by its tracking URI: these tests leave a decoy store as the
  process-global tracking URI, and the decoy must never be created.
* The train CLI's ALL line is the last line it prints.
* ``--json`` on a held-out run is bound by the held-out rule too: aggregates only, no case ids.

The store-backed fixture logs into NON-default experiments (``tellr-agent-eval`` and
``tellr-agent-eval-heldout``, as ``mlflow_run.run_sweep`` does) and then leaves the Default
experiment ("0") active, which is what a fresh ``python -m evals.intent_report`` process starts with.
``mlflow.search_traces(run_id=...)`` without ``locations=[run.info.experiment_id]`` therefore raises.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
import yaml

import src.core.database  # break import cycle before src.* imports  # noqa: F401

import mlflow
from mlflow.entities import Feedback, ViewType
from mlflow.genai.scorers import scorer
from mlflow.tracking import MlflowClient

from evals import intent_report as ir
from evals.harness import case as case_mod
from evals.harness import mlflow_run
from evals.harness import scorers as det
from evals.harness.case import Case

# Synthetic case ids: on no disk (so ``expect`` must come from the trace), and containing no intent
# name (so a CLI line that mentions "discuss" or "edit" does so because of its got_intents).
EDIT_CASE = "zq_alpha"
DISCUSS_CASE = "zq_beta"
CASE_IDS = (EDIT_CASE, DISCUSS_CASE)
FALLBACK_CASE = "zq_fallback"  # written to a tmp packs dir only; its runs log no "expect"

CONFIG_NAME = "v1-intent-probe"
CONTENT_HASH = "c0ffee123456" + "a" * 52
CASES_DIGEST = "d16e57abcdef" + "b" * 52

# The harness logs the model's full raw output; this makes every response far longer than the
# 1000-char trace preview, so only the span data parses as JSON.
BIG_RAW = {"text": "x" * 3000}

EXPECT = {
    EDIT_CASE: {"intent": "edit", "positions": [3, 1]},       # unsorted on purpose
    DISCUSS_CASE: {"intent": "discuss", "positions": [2]},    # positions are ignored unless edit
}
FALLBACK_EXPECT = {"train": {"intent": "edit", "positions": [1]},
                   "heldout": {"intent": "edit", "positions": [4]}}

# (case_id, repeat) -> (structured, infra_error)
SCRIPT = {
    (EDIT_CASE, 0): ({"intent": "edit", "message": "m", "target_positions": [3, 1, 3]}, False),  # right set
    (EDIT_CASE, 1): ({"intent": "edit", "message": "m", "target_positions": [2, 4]}, False),     # off by one
    (EDIT_CASE, 2): (None, True),                                                                  # infra error
    (DISCUSS_CASE, 0): ({"intent": "discuss", "message": "m", "target_positions": []}, False),
    (DISCUSS_CASE, 1): (None, False),                                                              # no output
    (FALLBACK_CASE, 0): ({"intent": "edit", "message": "m", "target_positions": [4]}, False),
}

SUMMARY_KEYS = {
    "rows", "intent_correct", "intent_accuracy", "no_output", "edit_rows",
    "positions_correct", "position_accuracy", "expected_category_pass",
}
ROW_KEYS = {"case_id", "expected_intent", "expected_positions", "got_intent", "got_positions",
            "expected_category"}

# What every main run (train and held-out) must report: the infra row skipped, 4 rows counted.
RUN_ALL = {"rows": 4, "intent_correct": 3, "intent_accuracy": 0.75, "no_output": 1, "edit_rows": 2,
           "positions_correct": 1, "position_accuracy": 0.5, "expected_category_pass": 2}
RUN_PER_CASE = {
    EDIT_CASE: {"rows": 2, "intent_correct": 2, "intent_accuracy": 1.0, "no_output": 0, "edit_rows": 2,
                "positions_correct": 1, "position_accuracy": 0.5, "expected_category_pass": 1,
                "got_intents": {"edit": 2}},
    DISCUSS_CASE: {"rows": 2, "intent_correct": 1, "intent_accuracy": 0.5, "no_output": 1, "edit_rows": 0,
                   "positions_correct": 0, "position_accuracy": None, "expected_category_pass": 1,
                   "got_intents": {"discuss": 1, "none": 1}},
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _row(case_id, expected_intent, expected_positions, got_intent, got_positions, expected_category):
    return {"case_id": case_id, "expected_intent": expected_intent, "expected_positions": expected_positions,
            "got_intent": got_intent, "got_positions": got_positions, "expected_category": expected_category}


def _assert_counts(actual: dict, expected: dict, *, where: str) -> None:
    """``actual[k]`` equals ``expected[k]`` for every expected key (floats approx, None exactly)."""
    for key, want in expected.items():
        assert key in actual, f"{where}: missing key {key!r}"
        got = actual[key]
        if want is None:
            assert got is None, f"{where}: {key} = {got!r}, expected None (denominator is 0)"
        elif isinstance(want, float):
            assert isinstance(got, (int, float)) and not isinstance(got, bool), f"{where}: {key} = {got!r}"
            assert got == pytest.approx(want), f"{where}: {key} = {got!r}, expected {want!r}"
        else:
            assert got == want, f"{where}: {key} = {got!r}, expected {want!r}"


def _assert_summary(summary: dict, overall: dict, per_case: dict) -> None:
    """The exact shape summarise() promises, and the exact values."""
    assert set(summary) == SUMMARY_KEYS | {"per_case"}
    _assert_counts(summary, overall, where="overall")
    assert set(summary["per_case"]) == set(per_case)
    for cid, want in per_case.items():
        got = summary["per_case"][cid]
        assert set(got) == SUMMARY_KEYS | {"got_intents"}, f"per_case[{cid!r}] keys"
        _assert_counts(got, want, where=f"per_case[{cid!r}]")


def _predict(agent_key: str, case_id: str, repeat: int, split: str = "train") -> dict:
    """The harness predict_fn's output shape (mlflow_run.make_predict_fn), scripted per row."""
    structured, infra = SCRIPT[(case_id, repeat)]
    return {
        "structured": structured,
        "raw": None if structured is None else BIG_RAW,
        "render": None,
        "latency_ms": 12.0,
        "input_tokens": 100,
        "output_tokens": 50,
        "status": "completed" if structured is not None else "model_error",
        "infra_error": infra,
        "error_detail": ("endpoint_unavailable: 503" if infra
                         else "invalid_output:ValidationError: no JSON" if structured is None else None),
    }


@scorer(name="contract")
def _contract(inputs, outputs, expectations):
    if outputs.get("infra_error"):
        return Feedback(value="skip", rationale="infra error")
    ok = outputs.get("structured") is not None
    return Feedback(value="pass" if ok else "fail", rationale="contract")


@scorer(name="expected_category")
def _expected_category(inputs, outputs, expectations):
    if outputs.get("infra_error"):
        return Feedback(value="skip", rationale="infra error")
    ok, why = det.expected_category_score(
        inputs["agent_key"], outputs.get("structured"), expectations.get("expect") or {})
    return Feedback(value="pass" if ok else "fail", rationale=why)


def _case(case_id: str, expect: dict) -> Case:
    return Case(case_id, "architect", "mutation", True, "", payload={},
                reference={"intent": expect["intent"]}, expect=expect)


def _main_dataset(split: str) -> list[dict]:
    """2 cases x 2 repeats through the harness's own build_dataset, plus 1 infra-error row."""
    data = mlflow_run.build_dataset([_case(cid, EXPECT[cid]) for cid in CASE_IDS], 2, split)
    infra_inputs = {"agent_key": "architect", "case_id": EDIT_CASE, "repeat": 2}
    if split != "train":
        infra_inputs["split"] = split
    data.append({"inputs": infra_inputs, "expectations": dict(data[0]["expectations"])})
    return data


def _fallback_dataset(split: str) -> list[dict]:
    """One row whose expectations carry no "expect": the report must load the case for ``split``."""
    data = mlflow_run.build_dataset([_case(FALLBACK_CASE, FALLBACK_EXPECT[split])], 1, split)
    for row in data:
        del row["expectations"]["expect"]
    return data


def _log_run(split: str, data: list[dict], *, repeats: int) -> str:
    mlflow.set_experiment(mlflow_run.EXPERIMENT_NAMES[split])  # never the Default experiment
    with mlflow.start_run(run_name=f"architect:{CONFIG_NAME}") as run:
        mlflow.set_tags({
            "agent_key": "architect", "config_name": CONFIG_NAME, "content_hash": CONTENT_HASH,
            "judge_endpoint": "stub-judge", "repeats": str(repeats), "case_filter": "all",
            "cases_digest": CASES_DIGEST, "split": split, "git_sha": "unknown",
        })
        mlflow.genai.evaluate(data=data, scorers=[_contract, _expected_category],
                              predict_fn=mlflow.trace(_predict))
    return run.info.run_id


def _traces(store, run_key: str) -> list:
    run_id = store.runs[run_key]
    client = MlflowClient(store.uri)
    exp_id = client.get_run(run_id).info.experiment_id
    return list(client.search_traces(run_id=run_id, locations=[exp_id], max_results=100))


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _store_snapshot(store) -> dict:
    """Everything a report could write: experiments, runs (tags/metrics/params/status), every
    trace's assessments, and the files under the store's root."""
    client = MlflowClient(store.uri)
    exps = sorted((e.experiment_id, e.name) for e in client.search_experiments(view_type=ViewType.ALL))
    runs, traces = {}, {}
    for exp_id, _ in exps:
        for r in client.search_runs([exp_id], run_view_type=ViewType.ALL, max_results=1000):
            runs[r.info.run_id] = (dict(r.data.tags), dict(r.data.metrics), dict(r.data.params), r.info.status)
        for t in client.search_traces(locations=[exp_id], max_results=100):
            traces[t.info.trace_id] = sorted(
                (a.name, json.dumps(getattr(a, "value", None), sort_keys=True, default=str))
                for a in t.info.assessments)
    files = sorted(p.relative_to(store.root).as_posix() for p in store.root.rglob("*")
                   if not p.name.endswith(("-journal", "-wal", "-shm")))
    return {"experiments": exps, "runs": runs, "traces": traces, "files": files}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """A tmp sqlite store holding four architect runs, built once per module:

    * ``heldout`` / ``train``: 2 cases x 2 repeats + 1 infra-error row (SCRIPT), in
      ``tellr-agent-eval-heldout`` / ``tellr-agent-eval``, tagged ``split``;
    * ``fallback_train`` / ``fallback_heldout``: one FALLBACK_CASE row with no "expect" expectation.
    """
    root = tmp_path_factory.mktemp("intent_report_store")
    uri = f"sqlite:///{root / 'mlflow.db'}"
    prev_uri = mlflow.get_tracking_uri()
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(root)  # mlflow's default ./mlruns artifact root lands here, never at the repo root
        for name in ("MLFLOW_EXPERIMENT_ID", "MLFLOW_EXPERIMENT_NAME"):
            mp.setenv(name, "registered-for-restore")  # mlflow.set_experiment writes MLFLOW_EXPERIMENT_ID;
            mp.delenv(name)                             # this pair restores the caller's value at teardown
        mp.setenv("MLFLOW_TRACKING_URI", uri)
        mp.setenv("MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION", "True")  # as run_sweep: no hidden extra trace
        mp.setenv("MLFLOW_GENAI_EVAL_MAX_WORKERS", "2")
        mlflow.set_tracking_uri(uri)
        try:
            runs = {
                "heldout": _log_run("heldout", _main_dataset("heldout"), repeats=2),
                "train": _log_run("train", _main_dataset("train"), repeats=2),
                "fallback_train": _log_run("train", _fallback_dataset("train"), repeats=1),
                "fallback_heldout": _log_run("heldout", _fallback_dataset("heldout"), repeats=1),
            }
            built = SimpleNamespace(uri=uri, root=root, runs=runs)
            built.pristine = _store_snapshot(built)  # before any test has read (or written) it
            yield built
        finally:
            mlflow.end_run()
            mlflow.set_tracking_uri(prev_uri)


@pytest.fixture
def reader(store, tmp_path, monkeypatch):
    """The state a fresh ``python -m evals.intent_report`` starts from: the Default experiment ("0",
    holding none of the runs) is active, and the process-global tracking URI and the harness default
    both name a decoy store, so only an explicit ``tracking_uri`` reaches the runs."""
    decoy = tmp_path / "decoy-mlflow.db"
    decoy_uri = f"sqlite:///{decoy}"
    mlflow.set_tracking_uri(store.uri)
    mlflow.set_experiment(experiment_id="0")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", decoy_uri)
    monkeypatch.setattr(mlflow_run, "default_tracking_uri", lambda: decoy_uri)
    mlflow.set_tracking_uri(decoy_uri)
    yield SimpleNamespace(store=store, decoy=decoy)
    mlflow.set_tracking_uri(store.uri)


# ---------------------------------------------------------------------------
# summarise: table-driven, one row each
# ---------------------------------------------------------------------------

SUMMARISE_TABLE = [
    pytest.param(
        _row("c", "edit", [1], "edit", [1], "pass"),
        {"rows": 1, "intent_correct": 1, "intent_accuracy": 1.0, "no_output": 0, "edit_rows": 1,
         "positions_correct": 1, "position_accuracy": 1.0, "expected_category_pass": 1},
        {"edit": 1},
        id="correct_edit"),
    pytest.param(
        # The ONLY row on which "intent from structured" and "intent from expected_category" disagree.
        _row("c", "edit", [1], "edit", [2], "fail"),
        {"rows": 1, "intent_correct": 1, "intent_accuracy": 1.0, "no_output": 0, "edit_rows": 1,
         "positions_correct": 0, "position_accuracy": 0.0, "expected_category_pass": 0},
        {"edit": 1},
        id="off_by_one_edit"),
    pytest.param(
        _row("c", "edit", [1], "discuss", [], "fail"),
        {"rows": 1, "intent_correct": 0, "intent_accuracy": 0.0, "no_output": 0, "edit_rows": 0,
         "positions_correct": 0, "position_accuracy": None, "expected_category_pass": 0},
        {"discuss": 1},
        id="polite_edit_answered_with_discuss"),
    pytest.param(
        _row("c", "discuss", [], "edit", [0], "fail"),
        {"rows": 1, "intent_correct": 0, "intent_accuracy": 0.0, "no_output": 0, "edit_rows": 0,
         "positions_correct": 0, "position_accuracy": None, "expected_category_pass": 0},
        {"edit": 1},
        id="discuss_answered_with_edit"),
    pytest.param(
        _row("c", "edit", [1], None, [], "fail"),
        {"rows": 1, "intent_correct": 0, "intent_accuracy": 0.0, "no_output": 1, "edit_rows": 0,
         "positions_correct": 0, "position_accuracy": None, "expected_category_pass": 0},
        {"none": 1},
        id="no_output"),
    pytest.param(
        _row("c", "edit", [1, 3], "edit", [3, 1, 3], "pass"),
        {"rows": 1, "intent_correct": 1, "intent_accuracy": 1.0, "no_output": 0, "edit_rows": 1,
         "positions_correct": 1, "position_accuracy": 1.0, "expected_category_pass": 1},
        {"edit": 1},
        id="multi_position_set_ignores_order_and_duplicates"),
]


@pytest.mark.parametrize("row, overall, got_intents", SUMMARISE_TABLE)
def test_summarise_one_row(row, overall, got_intents):
    summary = ir.summarise([row])
    _assert_summary(summary, overall, {"c": {**overall, "got_intents": got_intents}})


def test_summarise_empty_input_has_no_accuracies():
    summary = ir.summarise([])
    _assert_summary(
        summary,
        {"rows": 0, "intent_correct": 0, "intent_accuracy": None, "no_output": 0, "edit_rows": 0,
         "positions_correct": 0, "position_accuracy": None, "expected_category_pass": 0},
        {})


def test_summarise_groups_rows_per_case_and_counts_got_intents():
    rows = [
        _row("c_edit", "edit", [1], "edit", [1], "pass"),
        _row("c_discuss", "discuss", [], "edit", [0], "fail"),
        _row("c_edit", "edit", [1], "edit", [2], "fail"),            # off by one
        _row("c_polite", "edit", [2], "discuss", [], None),          # a run without the scorer
        _row("c_multi", "edit", [1, 3], "edit", [3, 1, 3], "pass"),
        _row("c_edit", "edit", [1], None, [], "fail"),               # no output
        _row("c_discuss", "discuss", [], "discuss", [], "pass"),
    ]
    _assert_summary(
        ir.summarise(rows),
        {"rows": 7, "intent_correct": 4, "intent_accuracy": 4 / 7, "no_output": 1, "edit_rows": 3,
         "positions_correct": 2, "position_accuracy": 2 / 3, "expected_category_pass": 3},
        {
            "c_edit": {"rows": 3, "intent_correct": 2, "intent_accuracy": 2 / 3, "no_output": 1,
                       "edit_rows": 2, "positions_correct": 1, "position_accuracy": 0.5,
                       "expected_category_pass": 1, "got_intents": {"edit": 2, "none": 1}},
            "c_polite": {"rows": 1, "intent_correct": 0, "intent_accuracy": 0.0, "no_output": 0,
                         "edit_rows": 0, "positions_correct": 0, "position_accuracy": None,
                         "expected_category_pass": 0, "got_intents": {"discuss": 1}},
            "c_discuss": {"rows": 2, "intent_correct": 1, "intent_accuracy": 0.5, "no_output": 0,
                          "edit_rows": 0, "positions_correct": 0, "position_accuracy": None,
                          "expected_category_pass": 1, "got_intents": {"edit": 1, "discuss": 1}},
            "c_multi": {"rows": 1, "intent_correct": 1, "intent_accuracy": 1.0, "no_output": 0,
                        "edit_rows": 1, "positions_correct": 1, "position_accuracy": 1.0,
                        "expected_category_pass": 1, "got_intents": {"edit": 1}},
        })


# ---------------------------------------------------------------------------
# row_from_trace and report over a real tmp store
# ---------------------------------------------------------------------------

def test_row_from_trace_reads_each_logged_trace(reader):
    by_row = {}
    for trace in _traces(reader.store, "heldout"):
        req = json.loads(trace.data.request)
        by_row[(req["case_id"], req["repeat"])] = ir.row_from_trace(trace, split="heldout")
    assert set(by_row) == set(SCRIPT) - {(FALLBACK_CASE, 0)}
    assert by_row.pop((EDIT_CASE, 2)) is None, "the infra-error row is not a counted row"

    got = {}
    for key, row in by_row.items():
        assert set(row) >= ROW_KEYS
        assert row["expected_positions"] == sorted(row["expected_positions"])
        assert row["got_positions"] == sorted(row["got_positions"])
        got[key] = (row["case_id"], row["expected_intent"], row["expected_positions"], row["got_intent"],
                    sorted(set(row["got_positions"])), row["expected_category"])
    assert got == {
        (EDIT_CASE, 0): (EDIT_CASE, "edit", [1, 3], "edit", [1, 3], "pass"),
        (EDIT_CASE, 1): (EDIT_CASE, "edit", [1, 3], "edit", [2, 4], "fail"),
        (DISCUSS_CASE, 0): (DISCUSS_CASE, "discuss", [], "discuss", [], "pass"),
        (DISCUSS_CASE, 1): (DISCUSS_CASE, "discuss", [], None, [], "fail"),
    }


def test_report_counts_a_heldout_run_and_skips_the_infra_row(reader):
    result = ir.report(reader.store.runs["heldout"], tracking_uri=reader.store.uri)
    _assert_counts(result, {**RUN_ALL, "infra_skipped": 1}, where="heldout report")
    assert not reader.decoy.exists(), "report read a store other than the one its tracking_uri names"


def test_report_counts_a_train_run_per_case(reader):
    result = ir.report(reader.store.runs["train"], tracking_uri=reader.store.uri)
    _assert_counts(result, {**RUN_ALL, "infra_skipped": 1}, where="train report")
    assert set(result["per_case"]) == set(CASE_IDS)
    for cid, want in RUN_PER_CASE.items():
        _assert_counts(result["per_case"][cid], want, where=f"train per_case[{cid!r}]")


def test_report_cases_restricts_the_rows_counted(reader):
    result = ir.report(reader.store.runs["train"], tracking_uri=reader.store.uri, cases=[DISCUSS_CASE])
    want = {k: v for k, v in RUN_PER_CASE[DISCUSS_CASE].items() if k != "got_intents"}
    _assert_counts(result, want, where="report(cases=[discuss case])")
    assert set(result["per_case"]) == {DISCUSS_CASE}


def test_report_without_tracking_uri_uses_the_harness_default(reader, monkeypatch):
    monkeypatch.setattr(mlflow_run, "default_tracking_uri", lambda: reader.store.uri)
    result = ir.report(reader.store.runs["heldout"])
    _assert_counts(result, {**RUN_ALL, "infra_skipped": 1}, where="report(tracking_uri=None)")


def test_expect_missing_from_the_trace_is_loaded_from_the_runs_split(reader, tmp_path, monkeypatch):
    packs = tmp_path / "packs"
    for split, expect in FALLBACK_EXPECT.items():
        d = packs / "architect" / case_mod.cases_dirname(split) / FALLBACK_CASE
        d.mkdir(parents=True)
        (d / "case.yaml").write_text(yaml.safe_dump(
            {"kind": "mutation", "fault": "", "expect": expect, "design_system_active": True}))
        (d / "payload.json").write_text("{}")
        (d / "reference.json").write_text(json.dumps({"intent": "edit"}))
    monkeypatch.setattr(case_mod, "PACKS_DIR", packs)

    [trace] = _traces(reader.store, "fallback_train")
    assert ir.row_from_trace(trace, split="train")["expected_positions"] == [1]
    assert ir.row_from_trace(trace, split="heldout")["expected_positions"] == [4]

    # report takes the split from the run's tag; both runs answered edit [4]
    train = ir.report(reader.store.runs["fallback_train"], tracking_uri=reader.store.uri)
    _assert_counts(train, {"rows": 1, "intent_correct": 1, "edit_rows": 1, "positions_correct": 0,
                           "position_accuracy": 0.0, "infra_skipped": 0}, where="fallback train")
    heldout = ir.report(reader.store.runs["fallback_heldout"], tracking_uri=reader.store.uri)
    _assert_counts(heldout, {"rows": 1, "intent_correct": 1, "edit_rows": 1, "positions_correct": 1,
                             "position_accuracy": 1.0, "infra_skipped": 0}, where="fallback heldout")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [[], ["--cases", EDIT_CASE]], ids=["all_cases", "cases_filter"])
def test_heldout_cli_prints_one_aggregate_line_and_no_case_id(reader, capsys, extra):
    capsys.readouterr()
    rc = ir.main(["--run-id", reader.store.runs["heldout"], "--tracking-uri", reader.store.uri, *extra])
    out, err = capsys.readouterr()
    assert rc == 0
    assert len(_lines(out)) == 1, f"held-out prints ONE aggregate line, got:\n{out}"
    for cid in CASE_IDS:
        assert cid not in out and cid not in err, f"held-out output names case {cid!r}"


def test_heldout_cli_json_has_the_aggregates_and_no_case_id(reader, capsys):
    capsys.readouterr()
    rc = ir.main(["--run-id", reader.store.runs["heldout"], "--tracking-uri", reader.store.uri, "--json"])
    out, err = capsys.readouterr()
    assert rc == 0
    _assert_counts(json.loads(out), {**RUN_ALL, "infra_skipped": 1}, where="held-out --json")
    for cid in CASE_IDS:
        assert cid not in out and cid not in err, f"held-out --json names case {cid!r}"


def test_train_cli_prints_a_header_one_line_per_case_and_an_all_line(reader, capsys):
    run_id = reader.store.runs["train"]
    capsys.readouterr()
    rc = ir.main(["--run-id", run_id, "--tracking-uri", reader.store.uri])
    lines = _lines(capsys.readouterr().out)
    assert rc == 0

    at = {}
    for cid in CASE_IDS:
        hits = [i for i, line in enumerate(lines) if cid in line]
        assert len(hits) == 1, f"case {cid!r} should get exactly one line, got {hits} in:\n" + "\n".join(lines)
        at[cid] = hits[0]
    all_hits = [i for i, line in enumerate(lines) if re.search(r"\bALL\b", line)]
    assert all_hits == [len(lines) - 1], "one ALL line, printed last:\n" + "\n".join(lines)
    assert all(cid not in lines[-1] for cid in CASE_IDS)

    header = "\n".join(lines[:min(at.values())])
    for token in (run_id, "train", CONFIG_NAME, CONTENT_HASH[:12], CASES_DIGEST[:12]):
        assert token in header, f"header lacks {token!r}:\n{header}"

    # got_intents on each case's line: the discuss case answered discuss once and nothing once
    assert "discuss" in lines[at[DISCUSS_CASE]] and "none" in lines[at[DISCUSS_CASE]]
    assert "edit" in lines[at[EDIT_CASE]] and "discuss" not in lines[at[EDIT_CASE]]

    capsys.readouterr()
    rc = ir.main(["--run-id", run_id, "--tracking-uri", reader.store.uri, "--cases", DISCUSS_CASE])
    lines = _lines(capsys.readouterr().out)
    assert rc == 0
    assert sum(DISCUSS_CASE in line for line in lines) == 1
    assert not any(EDIT_CASE in line for line in lines), "--cases restricts the case lines"
    assert sum(bool(re.search(r"\bALL\b", line)) for line in lines) == 1


def test_train_cli_json_is_the_report(reader, capsys):
    capsys.readouterr()
    rc = ir.main(["--run-id", reader.store.runs["train"], "--tracking-uri", reader.store.uri, "--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert rc == 0
    _assert_counts(parsed, {**RUN_ALL, "infra_skipped": 1}, where="train --json")
    for cid, want in RUN_PER_CASE.items():
        _assert_counts(parsed["per_case"][cid], want, where=f"train --json per_case[{cid!r}]")


def test_a_missing_sqlite_store_is_refused_not_created(tmp_path, monkeypatch, capsys):
    # Opening a sqlite URI whose file does not exist makes MLflow create an empty store; a typo'd
    # --tracking-uri must fail without leaving one behind.
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "mlflw.db"
    capsys.readouterr()
    rc = ir.main(["--run-id", "0" * 32, "--tracking-uri", f"sqlite:///{missing}"])
    assert rc == 1
    assert not missing.exists(), "the report created a store at a path that held none"
    assert str(missing) in capsys.readouterr().err


def test_report_and_cli_write_nothing(reader, capsys):
    # Compared with the snapshot taken when the store was built, so a write made by an earlier test's
    # report() call (same module-scoped store) is caught too, not absorbed into a "before" snapshot.
    for key in ("train", "heldout"):
        ir.report(reader.store.runs[key], tracking_uri=reader.store.uri)
        for extra in ([], ["--json"]):
            assert ir.main(["--run-id", reader.store.runs[key], "--tracking-uri", reader.store.uri, *extra]) == 0
    capsys.readouterr()
    assert _store_snapshot(reader.store) == reader.store.pristine
    assert not reader.decoy.exists()
