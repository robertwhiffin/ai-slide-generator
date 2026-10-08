"""Failing tests for held-out Task 2: the split plumbing through the judge, the MLflow run and the CLI.

Every case read in these tests goes through REAL on-disk tmp case trees: ``evals.harness.case.PACKS_DIR``
(and the ``PACKS_DIR`` names ``judge`` / ``mlflow_run`` imported from it) is monkeypatched to a tmp
``packs`` dir holding ``builder/cases`` (train) and ``builder/cases_heldout`` (heldout). The loaders are
NOT stubbed: stubbing them is exactly what would hide a split-blind by-id load.

Names this file FIXES for the implementer (see task-2-report.md, "names I fixed"):

* ``mlflow_run.EXPERIMENT_NAMES == {"train": "tellr-agent-eval", "heldout": "tellr-agent-eval-heldout"}``;
  ``mlflow_run.EXPERIMENT_NAME`` stays ``"tellr-agent-eval"``.
* ``run_sweep(..., split="train")`` keyword; run tag ``split`` = the split name.
* ``cases_digest(agent_key, root=None, *, split="train")``.
* ``build_dataset(cases, repeats, split="train")``: a held-out row's ``inputs["split"] == "heldout"``.
  A train row's split reads as ``inputs.get("split", "train") == "train"`` (the pre-existing
  ``test_build_dataset_rows_carry_inputs_and_expectations_per_case`` pins the DEFAULT row's ``inputs``
  keys to exactly ``{agent_key, case_id, repeat}``, so a default/train row omits the key).
* ``predict_fn(agent_key, case_id, repeat, split="train")``.
* ``judge.calibrate(agent_key, *, model=..., render_fn=None, split="train")`` and
  ``judge.load_calibration(agent_key, case_id, *, split="train")``.
* ``NoCasesError`` message contains the split name as a standalone word AND the split's directory
  (``.../cases_heldout``).
* CLI ``--split {train,heldout}`` (default train), passed to ``mlflow_run.run_sweep(split=...)`` and
  ``judge.calibrate(split=...)``.
* CLI held-out output: the CLI reads the run back from MLflow, using the SAME tracking URI it passed to
  ``run_sweep`` (``mlflow_run.default_tracking_uri()``, looked up at call time), and prints ONE line per
  agent, exactly::

      {agent}: run_id={run_id} pass_rate={pass_rate:.3f} infra_error_count={int} judge_error_count={int}

  with ``pass_rate=n/a`` when the run logged no ``pass_rate`` metric. Nothing else from the run (no
  per-case metrics, tags, case ids, rationales, payloads or references) is printed.
* Train CLI output is unchanged: ``{agent}: run_id={run_id}``.
"""
from __future__ import annotations

import json
import re
import threading

import pytest
import yaml

import src.core.database  # noqa: F401 - break import cycle before src.* imports

import mlflow
from mlflow.entities import Feedback
from mlflow.tracking import MlflowClient

import evals.run_eval as cli
from evals.harness import case as case_mod
from evals.harness import config
from evals.harness import judge as judge_mod
from evals.harness import mlflow_run
from evals.harness.runner import Runner
from tests.fixtures.deterministic_model_adapter import FAKE_OUTPUTS

AGENT = "builder"
JUDGE_EP = "stub-judge-endpoint"
TRAIN = "TRAIN_SENTINEL_7Q"
HELD = "HELDOUT_SENTINEL_3K"
RATIONALE = "RATIONALE_SENTINEL_9X"
JUDGE_BOOM = "JUDGE_BOOM_SENTINEL_4W"


# ---------------------------------------------------------------------------
# on-disk tmp case trees
# ---------------------------------------------------------------------------

def _payload(marker, cid, tag=""):
    return {
        "position": 1,
        "slide_spec": {"position": 1, "title": f"PAYLOAD-{marker}-{cid}{tag}", "purpose": "p"},
        "section_css": ".slide{}",
    }


def _reference(marker, cid):
    return {"position": 1, "html": f"<section class='slide'>REFERENCE-{marker}-{cid}</section>"}


def _should_fail(marker, cid):
    return {"position": 1, "html": f"<section class='slide'>SHOULDFAIL-{marker}-{cid}</section>"}


def _write_case(base, cid, marker, *, tag="", calibration=True):
    d = base / cid
    d.mkdir(parents=True)
    (d / "case.yaml").write_text(yaml.safe_dump(
        {"kind": "positive", "fault": "", "expect": {}, "design_system_active": True}))
    (d / "payload.json").write_text(json.dumps(_payload(marker, cid, tag)))
    (d / "reference.json").write_text(json.dumps(_reference(marker, cid)))
    if calibration:
        (d / "calibration.json").write_text(json.dumps({"should_fail": _should_fail(marker, cid)}))


@pytest.fixture
def packs(tmp_path, monkeypatch):
    """A tmp packs root; every module's PACKS_DIR points at it. Returns (train_dir, heldout_dir)."""
    root = tmp_path / "packs"
    (root / AGENT).mkdir(parents=True)
    (root / AGENT / "judge_prompt.md").write_text("judge {{ outputs }} {{ expectations }}")
    monkeypatch.setattr(case_mod, "PACKS_DIR", root)
    monkeypatch.setattr(judge_mod, "PACKS_DIR", root)
    monkeypatch.setattr(mlflow_run, "PACKS_DIR", root)
    return root / AGENT / "cases", root / AGENT / "cases_heldout"


@pytest.fixture
def collision_trees(packs):
    """Both splits hold a case id ``clean`` with distinguishable markers; each has one split-only case."""
    train, held = packs
    _write_case(train, "clean", TRAIN)
    _write_case(train, "tr_only", TRAIN)
    _write_case(held, "clean", HELD)
    _write_case(held, "ho_only", HELD)
    return train, held


@pytest.fixture
def tracking(tmp_path, monkeypatch):
    prev = mlflow.get_tracking_uri()
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION", raising=False)
    monkeypatch.setenv("MLFLOW_GENAI_EVAL_MAX_WORKERS", "1")
    yield uri
    mlflow.end_run()
    mlflow.set_tracking_uri(prev)


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------

class RecordingAdapter:
    """Records every prompt (the payload reaches the model only through it); valid builder output.

    A prompt containing ``INFRA`` raises a provider-unavailable error (an infra-error row).
    """

    def __init__(self):
        self.prompts = []
        self._lock = threading.Lock()

    def invoke(self, *, agent_key, configuration, schema, prompt):
        from src.services.agent_runtime import ModelProviderUnavailableError

        with self._lock:
            self.prompts.append(prompt)
        if "INFRA" in prompt:
            raise ModelProviderUnavailableError("503 endpoint down")
        out = dict(FAKE_OUTPUTS[agent_key])
        out["html"] = "<section class='slide'><h1>candidate</h1></section>"
        return schema.model_validate(out)


class RecordingJudge:
    """Records the ``expectations`` it is called with. Verdict keyed on the reference html:
    ``JFAIL`` -> fail, ``JERR`` -> raises, else pass. Every verdict carries RATIONALE."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
        blob = json.dumps(kwargs.get("expectations"), default=str)
        if "JERR" in blob:
            raise RuntimeError(JUDGE_BOOM)
        if "JFAIL" in blob:
            return Feedback(value="fail", rationale=RATIONALE)
        return Feedback(value="pass", rationale=RATIONALE)

    def expectations_blob(self):
        return json.dumps([c.get("expectations") for c in self.calls], default=str)

    def candidates_blob(self):
        return json.dumps([c.get("outputs") for c in self.calls], default=str)


def _patch_judge(monkeypatch, stub):
    monkeypatch.setattr(judge_mod, "build_judge", lambda *a, **k: stub)


def _sweep(monkeypatch, uri, split, *, case_filter=None, repeats=1):
    adapter, stub = RecordingAdapter(), RecordingJudge()
    _patch_judge(monkeypatch, stub)
    kwargs = {} if split is None else {"split": split}
    run_id = mlflow_run.run_sweep(
        config.v1_baseline(AGENT), agent_key=AGENT, repeats=repeats, max_workers=1,
        judge_endpoint=JUDGE_EP, case_filter=case_filter, render_enabled=False,
        runner=Runner(model_adapter=adapter, max_infra_retries=0), tracking_uri=uri, **kwargs)
    mlflow.set_tracking_uri(uri)
    return run_id, mlflow.get_run(run_id), adapter, stub


# ---------------------------------------------------------------------------
# THE CRITICAL ONE: same case id in both splits
# ---------------------------------------------------------------------------

def test_same_id_collision_heldout_sweep_reads_only_the_heldout_case(monkeypatch, tracking, collision_trees):
    _, run, adapter, stub = _sweep(monkeypatch, tracking, "heldout", case_filter=["clean"])
    prompts = "\n".join(adapter.prompts)
    expectations = stub.expectations_blob()

    # Guards the by-id load in make_predict_fn's predict_fn: the payload reaches the model ONLY via
    # predict_fn's load_case. Reverting the split there feeds the adapter the TRAIN payload.
    assert len(adapter.prompts) == 1
    assert f"PAYLOAD-{HELD}-clean" in prompts
    assert TRAIN not in prompts

    # Guards the by-id load in build_scorers' ``judge`` scorer: the judge's expectations are built from
    # the case that scorer loads (not from the dataset row). Reverting the split there hands the judge
    # the TRAIN reference and brief.
    assert len(stub.calls) == 1
    assert f"REFERENCE-{HELD}-clean" in expectations
    assert TRAIN not in expectations

    assert run.data.tags["split"] == "heldout"
    assert run.data.metrics["pass_rate"] == pytest.approx(1.0)


def test_same_id_collision_train_sweep_reads_only_the_train_case(monkeypatch, tracking, collision_trees):
    _, run, adapter, stub = _sweep(monkeypatch, tracking, "train", case_filter=["clean"])
    prompts = "\n".join(adapter.prompts)
    expectations = stub.expectations_blob()

    # predict_fn site (adapter recorder)
    assert len(adapter.prompts) == 1
    assert f"PAYLOAD-{TRAIN}-clean" in prompts
    assert HELD not in prompts
    # judge scorer site (judge recorder)
    assert len(stub.calls) == 1
    assert f"REFERENCE-{TRAIN}-clean" in expectations
    assert HELD not in expectations
    assert run.data.tags["split"] == "train"


def test_same_id_collision_full_heldout_sweep_never_touches_train(monkeypatch, tracking, collision_trees):
    _, _, adapter, stub = _sweep(monkeypatch, tracking, "heldout")
    prompts = "\n".join(adapter.prompts)
    expectations = stub.expectations_blob()
    assert len(adapter.prompts) == 2 and len(stub.calls) == 2
    assert f"PAYLOAD-{HELD}-clean" in prompts and f"PAYLOAD-{HELD}-ho_only" in prompts
    assert f"REFERENCE-{HELD}-clean" in expectations and f"REFERENCE-{HELD}-ho_only" in expectations
    assert TRAIN not in prompts
    assert TRAIN not in expectations


# ---------------------------------------------------------------------------
# predict_fn and the judge scorer, called directly
# ---------------------------------------------------------------------------

def test_predict_fn_split_kwarg_selects_the_tree_and_defaults_to_train(collision_trees):
    adapter = RecordingAdapter()
    pf = mlflow_run.make_predict_fn(
        config.v1_baseline(AGENT), Runner(model_adapter=adapter, max_infra_retries=0), render_enabled=False)
    out = pf(agent_key=AGENT, case_id="clean", repeat=0)  # no split: still works, train
    assert out["status"] == "completed"
    assert f"PAYLOAD-{TRAIN}-clean" in adapter.prompts[-1]
    pf(agent_key=AGENT, case_id="clean", repeat=0, split="heldout")
    assert f"PAYLOAD-{HELD}-clean" in adapter.prompts[-1]
    assert TRAIN not in adapter.prompts[-1]
    pf(agent_key=AGENT, case_id="clean", repeat=0, split="train")
    assert f"PAYLOAD-{TRAIN}-clean" in adapter.prompts[-1]


def _judge_scorer(monkeypatch):
    stub = RecordingJudge()
    _patch_judge(monkeypatch, stub)
    scorer = next(s for s in mlflow_run.build_scorers(AGENT, judge_endpoint=JUDGE_EP) if s.name == "judge")
    return scorer, stub


def _outputs():
    return {"structured": {"position": 1, "html": "<section/>"}, "raw": None, "render": None,
            "latency_ms": 1.0, "input_tokens": None, "output_tokens": None,
            "status": "completed", "infra_error": False}


def test_judge_scorer_loads_the_case_from_the_rows_split(monkeypatch, collision_trees):
    scorer, stub = _judge_scorer(monkeypatch)
    held = case_mod.load_case(AGENT, "clean", split="heldout")
    (row,) = mlflow_run.build_dataset([held], 1, split="heldout")
    fb = scorer.run(inputs=row["inputs"], outputs=_outputs(), expectations=row["expectations"])
    assert fb.value == "pass"
    blob = stub.expectations_blob()
    assert f"REFERENCE-{HELD}-clean" in blob
    assert TRAIN not in blob


def test_judge_scorer_row_without_split_is_train(monkeypatch, collision_trees):
    scorer, stub = _judge_scorer(monkeypatch)
    inputs = {"agent_key": AGENT, "case_id": "clean", "repeat": 0}
    scorer.run(inputs=inputs, outputs=_outputs(), expectations={})
    blob = stub.expectations_blob()
    assert f"REFERENCE-{TRAIN}-clean" in blob
    assert HELD not in blob


# ---------------------------------------------------------------------------
# build_dataset carries the split
# ---------------------------------------------------------------------------

def test_build_dataset_heldout_rows_carry_split(collision_trees):
    cases = case_mod.load_cases(AGENT, split="heldout")
    rows = mlflow_run.build_dataset(cases, 2, split="heldout")
    assert len(rows) == 4
    for r in rows:
        assert r["inputs"]["split"] == "heldout"
        assert {"agent_key", "case_id", "repeat"} <= set(r["inputs"])


@pytest.mark.parametrize("kwargs", [{}, {"split": "train"}])
def test_build_dataset_train_rows_read_as_train(collision_trees, kwargs):
    cases = case_mod.load_cases(AGENT)
    rows = mlflow_run.build_dataset(cases, 1, **kwargs)
    assert len(rows) == 2
    for r in rows:
        assert r["inputs"].get("split", "train") == "train"


# ---------------------------------------------------------------------------
# experiments, tags, digest
# ---------------------------------------------------------------------------

def test_experiment_names_mapping_and_legacy_constant():
    assert mlflow_run.EXPERIMENT_NAMES == {"train": "tellr-agent-eval", "heldout": "tellr-agent-eval-heldout"}
    assert mlflow_run.EXPERIMENT_NAME == "tellr-agent-eval"


def test_heldout_and_train_sweeps_log_to_separate_experiments(monkeypatch, tracking, collision_trees):
    _, held_run, _, _ = _sweep(monkeypatch, tracking, "heldout")
    _, train_run, _, _ = _sweep(monkeypatch, tracking, "train")
    held_exp = mlflow.get_experiment_by_name("tellr-agent-eval-heldout")
    train_exp = mlflow.get_experiment_by_name("tellr-agent-eval")
    assert held_exp is not None and train_exp is not None
    assert held_exp.experiment_id != train_exp.experiment_id
    assert held_run.info.experiment_id == held_exp.experiment_id
    assert train_run.info.experiment_id == train_exp.experiment_id
    assert held_run.data.tags["split"] == "heldout"
    assert train_run.data.tags["split"] == "train"


def test_default_sweep_is_train_experiment_and_tag(monkeypatch, tracking, collision_trees):
    _, run, adapter, _ = _sweep(monkeypatch, tracking, None)
    exp = mlflow.get_experiment_by_name("tellr-agent-eval")
    assert run.info.experiment_id == exp.experiment_id
    assert run.data.tags["split"] == "train"
    assert HELD not in "\n".join(adapter.prompts)
    assert mlflow.get_experiment_by_name("tellr-agent-eval-heldout") is None


def test_cases_digest_is_per_split(collision_trees):
    train, held = collision_trees
    d_train = mlflow_run.cases_digest(AGENT)
    d_held = mlflow_run.cases_digest(AGENT, split="heldout")
    assert d_train == mlflow_run.cases_digest(AGENT, split="train") == mlflow_run.cases_digest(AGENT, root=train)
    assert d_held == mlflow_run.cases_digest(AGENT, root=held)
    assert d_held != d_train


def test_run_sweep_tags_the_splits_cases_digest(monkeypatch, tracking, collision_trees):
    _, held_run, _, _ = _sweep(monkeypatch, tracking, "heldout")
    _, train_run, _, _ = _sweep(monkeypatch, tracking, "train")
    assert held_run.data.tags["cases_digest"] == mlflow_run.cases_digest(AGENT, split="heldout")
    assert train_run.data.tags["cases_digest"] == mlflow_run.cases_digest(AGENT, split="train")
    assert held_run.data.tags["cases_digest"] != train_run.data.tags["cases_digest"]


# ---------------------------------------------------------------------------
# --cases filter scope; empty held-out tree
# ---------------------------------------------------------------------------

def test_case_filter_cannot_select_a_train_only_id_in_a_heldout_sweep(monkeypatch, tracking, collision_trees):
    with pytest.raises(mlflow_run.NoCasesError):
        _sweep(monkeypatch, tracking, "heldout", case_filter=["tr_only"])


def test_case_filter_selects_the_heldout_only_id_within_heldout(monkeypatch, tracking, collision_trees):
    _, run, adapter, _ = _sweep(monkeypatch, tracking, "heldout", case_filter=["ho_only"])
    assert len(adapter.prompts) == 1
    assert f"PAYLOAD-{HELD}-ho_only" in adapter.prompts[0]
    assert set(k for k in run.data.metrics if k.startswith("pass_rate/")) == {"pass_rate/ho_only"}


@pytest.mark.parametrize("make_dir", [False, True])
def test_empty_heldout_tree_raises_no_cases_naming_heldout(monkeypatch, tracking, packs, make_dir):
    train, held = packs
    _write_case(train, "clean", TRAIN)  # train has cases; heldout has none
    if make_dir:
        held.mkdir(parents=True)
    with pytest.raises(mlflow_run.NoCasesError) as e:
        _sweep(monkeypatch, tracking, "heldout")
    msg = str(e.value)
    assert re.search(r"(?<![A-Za-z0-9_])heldout(?![A-Za-z0-9_])", msg), msg  # the split, as a word
    assert "cases_heldout" in msg, msg  # the split's directory
    mlflow.set_tracking_uri(tracking)
    exp = mlflow.get_experiment_by_name("tellr-agent-eval-heldout")
    assert exp is None or mlflow.search_runs([exp.experiment_id]).empty


# ---------------------------------------------------------------------------
# judge.calibrate / load_calibration
# ---------------------------------------------------------------------------

def test_load_calibration_reads_the_splits_file(collision_trees):
    assert judge_mod.load_calibration(AGENT, "clean") == {"should_fail": _should_fail(TRAIN, "clean")}
    assert judge_mod.load_calibration(AGENT, "clean", split="train") == {"should_fail": _should_fail(TRAIN, "clean")}
    assert judge_mod.load_calibration(AGENT, "clean", split="heldout") == {"should_fail": _should_fail(HELD, "clean")}
    assert judge_mod.load_calibration(AGENT, "ho_only", split="heldout") is not None
    assert judge_mod.load_calibration(AGENT, "ho_only") is None
    assert judge_mod.load_calibration(AGENT, "tr_only", split="heldout") is None


def _good_verdict_judge():
    """Pass the reference, fail anything else."""
    calls = []

    def stub(**kwargs):
        calls.append(kwargs)
        cand = json.dumps(kwargs.get("outputs"), default=str)
        return Feedback(value="pass" if "REFERENCE-" in cand else "fail", rationale=RATIONALE)

    return stub, calls


def test_calibrate_heldout_reads_heldout_cases_and_calibration(monkeypatch, collision_trees):
    stub, calls = _good_verdict_judge()
    monkeypatch.setattr(judge_mod, "build_judge", lambda *a, **k: stub)
    rows = judge_mod.calibrate(AGENT, split="heldout")
    assert [r["case_id"] for r in rows] == ["clean", "ho_only"]
    assert all(r["trusted"] for r in rows), rows  # ho_only's calibration exists ONLY in the heldout tree
    seen = json.dumps(calls, default=str)
    assert f"REFERENCE-{HELD}-clean" in seen
    assert f"SHOULDFAIL-{HELD}-clean" in seen  # held-out calibration.json, not train's
    assert TRAIN not in seen


@pytest.mark.parametrize("kwargs", [{}, {"split": "train"}])
def test_calibrate_train_is_unchanged(monkeypatch, collision_trees, kwargs):
    stub, calls = _good_verdict_judge()
    monkeypatch.setattr(judge_mod, "build_judge", lambda *a, **k: stub)
    rows = judge_mod.calibrate(AGENT, **kwargs)
    assert rows == [
        {"case_id": "clean", "reference_passed": True, "mutation_failed": True, "trusted": True, "reason": ""},
        {"case_id": "tr_only", "reference_passed": True, "mutation_failed": True, "trusted": True, "reason": ""},
    ]
    seen = json.dumps(calls, default=str)
    assert f"SHOULDFAIL-{TRAIN}-clean" in seen
    assert HELD not in seen


def test_calibrate_heldout_empty_tree_is_empty(monkeypatch, packs):
    train, _ = packs
    _write_case(train, "clean", TRAIN)
    monkeypatch.setattr(judge_mod, "build_judge", lambda *a, **k: _good_verdict_judge()[0])
    assert judge_mod.calibrate(AGENT, split="heldout") == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_env(monkeypatch, tracking):
    """No auth, reachable endpoint, the CLI's tracking URI is the tmp sqlite one."""
    monkeypatch.setattr(cli, "apply_profile", lambda profile: "https://h")
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: True)
    monkeypatch.setattr(mlflow_run, "default_tracking_uri", lambda: tracking)
    return tracking


class FakeSweep:
    """Stands in for run_sweep: creates a REAL MLflow run in the tracking URI it is given, with the
    metrics the CLI must read back, plus per-case metrics / tags the CLI must NOT print."""

    def __init__(self, metrics):
        self.metrics = metrics
        self.calls = []
        self.run_ids = []

    def __call__(self, cfg, **kw):
        self.calls.append((cfg, kw))
        client = MlflowClient(tracking_uri=kw["tracking_uri"])
        name = _EXPERIMENTS[kw.get("split", "train")]
        exp = client.get_experiment_by_name(name)
        exp_id = exp.experiment_id if exp else client.create_experiment(name)
        rid = client.create_run(exp_id).info.run_id
        for k, v in self.metrics.items():
            client.log_metric(rid, k, v)
        client.set_tag(rid, "leaky_tag", f"PAYLOAD-{HELD}-leak")
        client.set_terminated(rid)
        self.run_ids.append(rid)
        return rid


_EXPERIMENTS = {"train": "tellr-agent-eval", "heldout": "tellr-agent-eval-heldout"}

HELD_METRICS = {"pass_rate": 0.25, "infra_error_count": 3, "judge_error_count": 4,
                "pass_rate/hoq7_leakcase": 0.0, "mean_latency_ms": 12.5}


def test_cli_split_bogus_exits_nonzero(cli_env, monkeypatch):
    sweep = FakeSweep(HELD_METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", AGENT, "--split", "bogus"])
    assert e.value.code not in (0, None)
    assert sweep.calls == []


def test_cli_split_heldout_passes_through_and_prints_the_summary_read_from_mlflow(cli_env, monkeypatch, capsys):
    sweep = FakeSweep(HELD_METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli.main(["--agent", AGENT, "--split", "heldout"])
    (_, kw), = sweep.calls
    assert kw["split"] == "heldout"
    assert kw["tracking_uri"] == cli_env
    out = capsys.readouterr().out
    rid = sweep.run_ids[0]
    assert out.strip().splitlines() == [
        f"{AGENT}: run_id={rid} pass_rate=0.250 infra_error_count=3 judge_error_count=4"]
    assert "hoq7_leakcase" not in out and HELD not in out and "12.5" not in out


def test_cli_heldout_pass_rate_absent_prints_na(cli_env, monkeypatch, capsys):
    sweep = FakeSweep({"infra_error_count": 2, "judge_error_count": 0})
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli.main(["--agent", AGENT, "--split", "heldout"])
    out = capsys.readouterr().out
    assert out.strip().splitlines() == [
        f"{AGENT}: run_id={sweep.run_ids[0]} pass_rate=n/a infra_error_count=2 judge_error_count=0"]


@pytest.mark.parametrize("extra", [[], ["--split", "train"]])
def test_cli_train_output_is_unchanged(cli_env, monkeypatch, capsys, extra):
    sweep = FakeSweep(HELD_METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli.main(["--agent", AGENT, *extra])
    (_, kw), = sweep.calls
    assert kw.get("split", "train") == "train"
    assert capsys.readouterr().out.strip().splitlines() == [f"{AGENT}: run_id={sweep.run_ids[0]}"]


@pytest.mark.parametrize("extra,expected", [([], "train"), (["--split", "train"], "train"),
                                            (["--split", "heldout"], "heldout")])
def test_cli_calibrate_passes_split_and_keeps_the_trust_table(cli_env, monkeypatch, capsys, extra, expected):
    cal = []
    monkeypatch.setattr(judge_mod, "calibrate", lambda *a, **k: cal.append((a, k)) or [
        {"case_id": "case-zz9", "reference_passed": True, "mutation_failed": True,
         "trusted": True, "reason": ""}])
    sweep = FakeSweep(HELD_METRICS)
    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli.main(["--agent", "architect", "--calibrate", *extra])
    assert sweep.calls == []
    (_, kw), = cal
    assert kw.get("split", "train") == expected
    out = capsys.readouterr().out
    assert "case-zz9" in out and "ref_passed" in out and "trusted" in out  # columns unchanged


@pytest.fixture
def cli_trees(packs):
    """Held-out: one pass, one judge-fail, one judge-error, two infra errors -> pass_rate 0.5, infra 2,
    judge 1. Train (same agent): all passing -> a split-blind CLI would report pass_rate 1.0, infra 0."""
    train, held = packs
    _write_case(held, "hoq7_pass", HELD)
    _write_case(held, "hoq7_fail", HELD + "_JFAIL")
    _write_case(held, "hoq7_jerr", HELD + "_JERR")
    _write_case(held, "hoq7_inf1", HELD, tag="_INFRA")
    _write_case(held, "hoq7_inf2", HELD, tag="_INFRA")
    _write_case(train, "hoq7_pass", TRAIN)
    _write_case(train, "trq7_other", TRAIN)
    return train, held


def _cli_real_sweep(monkeypatch):
    adapter, stub = RecordingAdapter(), RecordingJudge()
    _patch_judge(monkeypatch, stub)
    monkeypatch.setattr(mlflow_run, "Runner", lambda *a, **k: Runner(model_adapter=adapter, max_infra_retries=0))
    return adapter, stub


def test_cli_heldout_end_to_end_prints_only_the_summary(cli_env, cli_trees, monkeypatch, capsys):
    adapter, stub = _cli_real_sweep(monkeypatch)
    cli.main(["--agent", AGENT, "--split", "heldout", "--repeats", "1", "--max-workers", "1", "--no-render"])
    out = capsys.readouterr().out

    mlflow.set_tracking_uri(cli_env)
    exp = mlflow.get_experiment_by_name("tellr-agent-eval-heldout")
    assert exp is not None
    runs = mlflow.search_runs([exp.experiment_id], output_format="list")
    assert len(runs) == 1
    rid = runs[0].info.run_id
    assert runs[0].data.tags["split"] == "heldout"
    assert len(adapter.prompts) == 5 and TRAIN not in "\n".join(adapter.prompts)

    summary = f"{AGENT}: run_id={rid} pass_rate=0.500 infra_error_count=2 judge_error_count=1"
    assert summary in out.splitlines(), out
    for forbidden in ("hoq7_", "trq7_", RATIONALE, JUDGE_BOOM, HELD, TRAIN,
                      "PAYLOAD-", "REFERENCE-", "SHOULDFAIL-", "slide_spec", "<section"):
        assert forbidden not in out, (forbidden, out)


def test_cli_train_end_to_end_output_is_the_run_id_line(cli_env, cli_trees, monkeypatch, capsys):
    _cli_real_sweep(monkeypatch)
    cli.main(["--agent", AGENT, "--repeats", "1", "--max-workers", "1", "--no-render"])
    out = capsys.readouterr().out
    mlflow.set_tracking_uri(cli_env)
    exp = mlflow.get_experiment_by_name("tellr-agent-eval")
    (run,) = mlflow.search_runs([exp.experiment_id], output_format="list")
    assert run.data.tags["split"] == "train"
    assert f"{AGENT}: run_id={run.info.run_id}" in out.splitlines(), out
    assert "pass_rate=" not in out
