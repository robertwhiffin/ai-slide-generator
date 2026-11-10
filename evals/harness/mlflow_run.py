"""MLflow genai.evaluate assembly for the agent-configuration eval harness."""
from __future__ import annotations

import dataclasses
import hashlib
import os
import pathlib
import statistics
import subprocess
from collections import defaultdict
from typing import Callable

import mlflow
from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer

import src.core.database  # noqa: F401 - break import cycle before src.* imports
from evals.harness import judge as judge_mod  # aliased: "judge" is also a scorer name
from evals.harness import scorers as det
from evals.harness.case import (
    EVALS_DIR,
    PACKS_DIR,
    Case,
    case_set_dir,
    cases_dirname,
    load_case,
    load_cases,
    meridian_section_css,
    split_kwargs,
)
from evals.harness.config import IMAGE_TOOL_ROLES, AgentEvalConfig, prices
from evals.harness.render import RenderMeasures, render_slide
from evals.harness.runner import Runner

HTML_ROLES = ("builder", "fixer")
DETERMINISTIC_CATEGORY_ROLES = (
    "architect", "data_analyst", "build_reviewer", "fix_reviewer", "deck_reviewer")
EXPERIMENT_NAME = "tellr-agent-eval"
EXPERIMENT_NAMES = {"train": "tellr-agent-eval", "heldout": "tellr-agent-eval-heldout"}
NOT_COMPARABLE_INFRA_RATE = 0.10
#: The run metric that isolates the ``image_tool`` scorer's pass rate (chat image generation).
IMAGE_TOOL_METRIC = "image_tool_pass_rate"


class NoCasesError(ValueError):
    """The pack (or the --cases filter) yields no cases; nothing to evaluate."""


def default_tracking_uri() -> str:
    return f"sqlite:///{EVALS_DIR.parent / 'mlflow.db'}"


# --------------------------------------------------------------------------- run identity

def cases_digest(agent_key: str, root: pathlib.Path | None = None, *, split: str = "train") -> str:
    """sha256 over the agent's committed ``cases/`` tree: each file's relative path and bytes, in
    sorted relative-path order. Runs are comparable only when their ``cases_digest`` tags match."""
    base = pathlib.Path(root) if root is not None else PACKS_DIR / agent_key / cases_dirname(split)
    h = hashlib.sha256()
    files = sorted((p.relative_to(base).as_posix(), p) for p in base.rglob("*") if p.is_file())
    for rel, path in files:
        h.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def git_sha() -> str:
    """``git rev-parse HEAD`` of the repo, or "unknown"."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=EVALS_DIR.parent,
                             capture_output=True, text=True, check=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - no git, not a checkout, ...
        return "unknown"


def mark_superseded(tracking_uri: str, experiment_name: str, reason: str) -> int:
    """Tag every existing run in ``experiment_name`` superseded=true with ``reason``; return the
    count."""
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=tracking_uri)
    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        return 0
    n = 0
    token = None
    while True:
        page = client.search_runs([exp.experiment_id], run_view_type=mlflow.entities.ViewType.ALL,
                                  max_results=1000, page_token=token)
        for run in page:
            client.set_tag(run.info.run_id, "superseded", "true")
            client.set_tag(run.info.run_id, "superseded_reason", reason)
            n += 1
        token = page.token
        if not token:
            return n


# --------------------------------------------------------------------------- pure helpers

def pass_rate(values: list[str]) -> float | None:
    """passing / (passing + failing); skip rows excluded; None when nothing counted."""
    p = sum(1 for v in values if v == "pass")
    f = sum(1 for v in values if v == "fail")
    return p / (p + f) if (p + f) else None


def row_outcome(values: dict[str, str]) -> str:
    if values.get("judge") == "skip":
        return "skip"
    if all(v == "skip" for v in values.values()):
        return "skip"
    if any(v == "fail" for v in values.values()):
        return "fail"
    return "pass"


def case_kwargs(agent_key: str, split: str = "train", case_set: str | None = None) -> dict:
    """Keyword args that load a row's case: none for the train set (the default), ``split`` for
    held-out, ``root`` for a named case set (``case.case_set_dir``)."""
    if case_set is not None:
        return {"root": case_set_dir(agent_key, case_set)}
    return split_kwargs(split)


def _row_case(inputs: dict) -> Case:
    """The case a dataset row was built from, read the way ``predict_fn`` reads it."""
    return load_case(inputs["agent_key"], inputs["case_id"], **case_kwargs(
        inputs["agent_key"], inputs.get("split", "train"), inputs.get("case_set")))


def build_dataset(
    cases: list[Case], repeats: int, split: str = "train", case_set: str | None = None
) -> list[dict]:
    rows = []
    for c in cases:
        for r in range(repeats):
            inputs = {"agent_key": c.agent_key, "case_id": c.case_id, "repeat": r}
            if split != "train":
                # train rows omit the key; readers use inputs.get("split", "train")
                inputs["split"] = split
            if case_set is not None:
                inputs["case_set"] = case_set  # likewise only on a named case set's rows
            expectations = {
                "expect": c.expect,
                "reference": c.reference,
                "design_system_active": c.design_system_active,
            }
            deck = (c.payload or {}).get("current_deck_spec")
            if c.agent_key == "architect" and deck is not None:
                # The insert scorer aligns the output against the deck the turn started from.
                expectations["current_deck_spec"] = deck
            rows.append({"inputs": inputs, "expectations": expectations})
    return rows


# --------------------------------------------------------------------------- predict

def render_section_css(case: Case) -> str:
    """The CSS a case's slide is rendered with: Meridian's, then the deck style's when the case
    payload carries one, as production writes the deck style into deck.css after the template's
    (C21). Both render paths use it: ``predict_fn`` and ``run_eval``'s calibration render."""
    css = meridian_section_css()
    style = (case.payload or {}).get("deck_style")
    if style:
        css += "\n\n" + style["css"]
    return css


def make_predict_fn(config: AgentEvalConfig, runner: Runner, *, render_enabled: bool) -> Callable:
    def predict_fn(
        agent_key: str, case_id: str, repeat: int, split: str = "train",
        case_set: str | None = None,
    ) -> dict:
        case = load_case(agent_key, case_id, **case_kwargs(agent_key, split, case_set))
        result = runner.run(config, case.payload, design_system_active=case.design_system_active)
        render = None
        if (render_enabled and agent_key in HTML_ROLES and not result.infra_error
                and isinstance(result.structured, dict) and "html" in result.structured):
            m = render_slide(
                result.structured["html"], result.structured.get("scripts") or "",
                section_css=render_section_css(case),
            )
            render = dataclasses.asdict(m)
        return {
            "structured": result.structured,
            "raw": result.raw,
            "render": render,
            "latency_ms": result.latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "status": result.status,
            "infra_error": result.infra_error,
            "error_detail": result.error_detail,
            # The run's tool calls (``RunResult.tool_calls``): brand-asset searches, which
            # render_measures reads for a brand-asset case, or image calls, which image_tool
            # reads; a runner result written before the field existed has none.
            "tool_calls": list(getattr(result, "tool_calls", ()) or ()),
        }

    return predict_fn


# --------------------------------------------------------------------------- scorers

def _fb(ok: bool, rationale: str) -> Feedback:
    return Feedback(value="pass" if ok else "fail", rationale=rationale)


def _skip(rationale: str) -> Feedback:
    return Feedback(value="skip", rationale=rationale)


def _render_from(outputs: dict) -> RenderMeasures | None:
    r = outputs.get("render")
    if r is None:
        return None
    r = dict(r)
    r["off_palette"] = tuple(r.get("off_palette") or ())
    r["console_errors"] = tuple(r.get("console_errors") or ())
    return RenderMeasures(**r)


def build_scorers(agent_key: str, *, judge_endpoint: str, image_tool: bool = False) -> list:
    """The row scorers for ``agent_key``. ``image_tool`` adds the architect's ``image_tool``
    scorer (``run_sweep`` asks for it when the config binds the tool or a swept case expects it);
    every other list is unchanged."""
    judge_obj = judge_mod.build_judge(agent_key, model=judge_endpoint)

    @scorer(name="contract")
    def contract(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        return _fb(*det.contract_score(
            outputs.get("structured"),
            status=outputs.get("status"),
            error_detail=outputs.get("error_detail"),
        ))

    @scorer(name="expected_category")
    def expected_category(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        return _fb(*det.expected_category_score(
            inputs["agent_key"], outputs.get("structured"), expectations.get("expect") or {},
            reference=expectations.get("reference"),
            current_deck_spec=expectations.get("current_deck_spec"),
            design_system_active=expectations.get("design_system_active")))

    @scorer(name="render_measures")
    def render_measures(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        m = _render_from(outputs)
        if m is None:
            return _skip("no render for this row")
        html = (outputs.get("structured") or {}).get("html", "")
        ok, why = det.render_measures_score(m, html)
        # A case whose slide is built on a deck style also scores its use (C21): the payload, which
        # holds the deck style and the template CSS, is the row's own case's. A brand-asset case
        # (Addendum A) also scores the icons it places against the run's searches. Each is ANDed:
        # a failing row names only what failed; a passing row names every check.
        case = _row_case(inputs)
        expect = case.expect or {}
        checks = []
        if "deck_style_classes" in expect:
            checks.append(det.deck_style_use_score(html, case.payload or {}, expect))
        if "brand_assets" in expect:
            checks.append(det.brand_asset_use_score(
                html, case.payload or {}, expect, tool_calls=outputs.get("tool_calls")))
        for check_ok, check_why in checks:
            if not check_ok:
                why = check_why if ok else f"{why}; {check_why}"
            elif ok:
                why = f"{why}; {check_why}"
            ok = ok and check_ok
        return _fb(ok, why)

    @scorer(name="judge")
    def judge(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        structured = outputs.get("structured")
        if structured is None:
            return _fb(False, "no candidate output to judge")
        case = _row_case(inputs)
        v, detail = judge_mod._verdict(judge_obj, case, structured, _render_from(outputs))
        if v == "error":
            return _skip(f"judge_error: {detail}")  # never retried, never pass/fail
        return _fb(v == "pass", detail or "judge verdict (no rationale given)")

    @scorer(name="image_tool")
    def image_tool_scorer(inputs, outputs, expectations):
        # A case with no image-tool expectation asks for no image: on a run that binds the tool,
        # it is scored as "no call" (the tool must not disturb the turn).
        if outputs.get("infra_error"):
            return _skip("infra error")
        expect = expectations.get("expect") or {}
        if "image_tool" not in expect:
            expect = {"image_tool": {"called": False}}
        return _fb(*det.image_tool_score(
            outputs.get("structured"), expect, tool_calls=outputs.get("tool_calls"),
            current_deck_spec=expectations.get("current_deck_spec")))

    out = [contract]
    if agent_key in DETERMINISTIC_CATEGORY_ROLES:
        out.append(expected_category)
    if agent_key in HTML_ROLES:
        out.append(render_measures)
    if image_tool and agent_key in IMAGE_TOOL_ROLES:
        out.append(image_tool_scorer)
    out.append(judge)
    return out


# --------------------------------------------------------------------------- sweep

def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def run_sweep(
    config: AgentEvalConfig,
    *,
    agent_key: str,
    repeats: int,
    max_workers: int,
    judge_endpoint: str,
    case_filter: list[str] | None = None,
    render_enabled: bool = True,
    runner: Runner | None = None,
    tracking_uri: str | None = None,
    split: str = "train",
    case_set: str | None = None,
) -> str:
    """Sweep ``config`` over the agent's cases and log one MLflow run; return its id.

    ``case_set`` names a case set kept apart from the splits (``case.case_set_dir``) to sweep
    instead of the train cases; it has no held-out split. The ``image_tool`` scorer is added
    when the config binds the image tool or a swept case expects it; only then is
    ``IMAGE_TOOL_METRIC`` logged, and the ``image_tool`` / ``case_set`` tags only when set.
    """
    if case_set is not None and split != "train":
        raise ValueError(f"case set {case_set!r} has no {split!r} split; sweep it as train")
    cases = load_cases(agent_key, **case_kwargs(agent_key, split, case_set))
    if case_filter:
        wanted = {str(c) for c in case_filter}
        cases = [c for c in cases if c.case_id in wanted]
    if not cases:
        where = (case_set_dir(agent_key, case_set) if case_set is not None
                 else PACKS_DIR / agent_key / cases_dirname(split))
        split_note = "" if split == "train" else f" (split {split})"
        raise NoCasesError(
            f"no cases for agent {agent_key!r}{split_note} under {where}"
            + (f" matching --cases {sorted(wanted)}" if case_filter else ""))
    os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = str(max_workers)
    os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "True"
    mlflow.set_tracking_uri(tracking_uri or default_tracking_uri())
    mlflow.set_experiment(EXPERIMENT_NAMES[split])
    data = build_dataset(cases, repeats, split, case_set=case_set)
    runner = runner or Runner()
    predict_fn = mlflow.trace(make_predict_fn(config, runner, render_enabled=render_enabled))
    image_tool = config.image_tool or any("image_tool" in (c.expect or {}) for c in cases)
    scorers = build_scorers(agent_key, judge_endpoint=judge_endpoint, image_tool=image_tool)

    with mlflow.start_run(run_name=f"{agent_key}:{config.name}") as run:
        mlflow.set_tags({
            "agent_key": agent_key,
            "config_name": config.name,
            "content_hash": config.content_hash,
            "judge_endpoint": judge_endpoint,
            "repeats": str(repeats),
            "case_filter": ",".join(case_filter) if case_filter else "all",
            "cases_digest": cases_digest(
                agent_key,
                case_set_dir(agent_key, case_set) if case_set is not None else None,
                split=split),
            "split": split,
            "git_sha": git_sha(),
        })
        if config.image_tool:
            mlflow.set_tag("image_tool", "true")
        if case_set is not None:
            mlflow.set_tag("case_set", case_set)
        result = mlflow.genai.evaluate(data=data, scorers=scorers, predict_fn=predict_fn)
        df = result.result_df

        names = [s.name for s in scorers]
        per_case: dict[str, list[str]] = defaultdict(list)
        outcomes: list[str] = []
        image_tool_values: list[str] = []
        latencies, in_toks, out_toks = [], [], []
        infra = judge_err = non_infra = 0
        cost = 0.0
        cost_known = False
        price = prices().get(config.content.model.endpoint_name)
        for _, row in df.iterrows():
            req, resp = row["request"], row["response"]
            vals = {n: row[f"{n}/value"] for n in names}
            o = row_outcome(vals)
            outcomes.append(o)
            if "image_tool" in vals:
                image_tool_values.append(vals["image_tool"])
            per_case[req["case_id"]].append(o)
            if resp.get("infra_error"):
                infra += 1
                continue
            non_infra += 1
            if vals.get("judge") == "skip":
                judge_err += 1
            latencies.append(resp.get("latency_ms"))
            in_toks.append(resp.get("input_tokens"))
            out_toks.append(resp.get("output_tokens"))
            if price and isinstance(resp.get("input_tokens"), (int, float)) \
                    and isinstance(resp.get("output_tokens"), (int, float)):
                cost += (resp["input_tokens"] * price["input_per_1k"]
                         + resp["output_tokens"] * price["output_per_1k"]) / 1000
                cost_known = True

        overall = pass_rate(outcomes)
        if overall is not None:
            mlflow.log_metric("pass_rate", overall)
        image_tool_rate = pass_rate(image_tool_values)
        if image_tool_rate is not None:
            mlflow.log_metric(IMAGE_TOOL_METRIC, image_tool_rate)
        stds = []
        for cid, outs in per_case.items():
            pr = pass_rate(outs)
            if pr is not None:
                mlflow.log_metric(f"pass_rate/{cid}", pr)
                bin_ = [1.0 if o == "pass" else 0.0 for o in outs if o != "skip"]
                stds.append(statistics.pstdev(bin_))
        if stds:
            mlflow.log_metric("repeat_stddev", statistics.mean(stds))
        mlflow.log_metric("infra_error_count", infra)
        mlflow.log_metric("judge_error_count", judge_err)
        lat = sorted(_num(latencies))
        if lat:
            mlflow.log_metric("mean_latency_ms", statistics.mean(lat))
            mlflow.log_metric("p95_latency_ms", lat[min(len(lat) - 1, int(0.95 * len(lat)))])
        if _num(in_toks):
            mlflow.log_metric("mean_input_tokens", statistics.mean(_num(in_toks)))
        if _num(out_toks):
            mlflow.log_metric("mean_output_tokens", statistics.mean(_num(out_toks)))
        if cost_known:
            mlflow.log_metric("est_cost_usd", cost)
        total = len(outcomes)
        if total and infra / total > NOT_COMPARABLE_INFRA_RATE:
            mlflow.set_tag("not_comparable", "true")
        if non_infra and judge_err == non_infra:
            mlflow.set_tag("judge_unavailable", "true")
        return run.info.run_id
