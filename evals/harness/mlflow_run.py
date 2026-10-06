"""MLflow genai.evaluate assembly for the agent-configuration eval harness."""
from __future__ import annotations

import dataclasses
import os
import statistics
from collections import defaultdict
from typing import Callable

import src.core.database  # noqa: F401 - break import cycle before src.* imports

import mlflow
from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer

from evals.harness import judge as judge_mod  # aliased: "judge" is also a scorer name
from evals.harness import scorers as det
from evals.harness.case import EVALS_DIR, PACKS_DIR, Case, load_case, load_cases, meridian_section_css
from evals.harness.config import AgentEvalConfig, prices
from evals.harness.render import RenderMeasures, render_slide
from evals.harness.runner import Runner

HTML_ROLES = ("builder", "fixer")
DETERMINISTIC_CATEGORY_ROLES = ("architect", "data_analyst", "build_reviewer", "fix_reviewer", "deck_reviewer")
EXPERIMENT_NAME = "tellr-agent-eval"
NOT_COMPARABLE_INFRA_RATE = 0.10


class NoCasesError(ValueError):
    """The pack (or the --cases filter) yields no cases; nothing to evaluate."""


def default_tracking_uri() -> str:
    return f"sqlite:///{EVALS_DIR.parent / 'mlflow.db'}"


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


def build_dataset(cases: list[Case], repeats: int) -> list[dict]:
    rows = []
    for c in cases:
        for r in range(repeats):
            rows.append({
                "inputs": {"agent_key": c.agent_key, "case_id": c.case_id, "repeat": r},
                "expectations": {
                    "expect": c.expect,
                    "reference": c.reference,
                    "design_system_active": c.design_system_active,
                },
            })
    return rows


# --------------------------------------------------------------------------- predict

def make_predict_fn(config: AgentEvalConfig, runner: Runner, *, render_enabled: bool) -> Callable:
    def predict_fn(agent_key: str, case_id: str, repeat: int) -> dict:
        case = load_case(agent_key, case_id)
        result = runner.run(config, case.payload, design_system_active=case.design_system_active)
        render = None
        if (render_enabled and agent_key in HTML_ROLES and not result.infra_error
                and isinstance(result.structured, dict) and "html" in result.structured):
            m = render_slide(
                result.structured["html"], result.structured.get("scripts") or "",
                section_css=meridian_section_css(),
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


def build_scorers(agent_key: str, *, judge_endpoint: str) -> list:
    judge_obj = judge_mod.build_judge(agent_key, model=judge_endpoint)

    @scorer(name="contract")
    def contract(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        return _fb(*det.contract_score(outputs.get("structured")))

    @scorer(name="expected_category")
    def expected_category(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        return _fb(*det.expected_category_score(
            inputs["agent_key"], outputs.get("structured"), expectations.get("expect") or {}))

    @scorer(name="render_measures")
    def render_measures(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        m = _render_from(outputs)
        if m is None:
            return _skip("no render for this row")
        html = (outputs.get("structured") or {}).get("html", "")
        return _fb(*det.render_measures_score(m, html))

    @scorer(name="judge")
    def judge(inputs, outputs, expectations):
        if outputs.get("infra_error"):
            return _skip("infra error")
        structured = outputs.get("structured")
        if structured is None:
            return _fb(False, "no candidate output to judge")
        case = load_case(inputs["agent_key"], inputs["case_id"])
        v, detail = judge_mod._verdict(judge_obj, case, structured, _render_from(outputs))
        if v == "error":
            return _skip(f"judge_error: {detail}")  # never retried, never pass/fail
        return _fb(v == "pass", "judge verdict")

    out = [contract]
    if agent_key in DETERMINISTIC_CATEGORY_ROLES:
        out.append(expected_category)
    if agent_key in HTML_ROLES:
        out.append(render_measures)
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
) -> str:
    cases = load_cases(agent_key)
    if case_filter:
        wanted = {str(c) for c in case_filter}
        cases = [c for c in cases if c.case_id in wanted]
    if not cases:
        where = PACKS_DIR / agent_key / "cases"
        raise NoCasesError(
            f"no cases for agent {agent_key!r} under {where}"
            + (f" matching --cases {sorted(wanted)}" if case_filter else ""))
    os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = str(max_workers)
    os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "True"
    mlflow.set_tracking_uri(tracking_uri or default_tracking_uri())
    mlflow.set_experiment(EXPERIMENT_NAME)
    data = build_dataset(cases, repeats)
    runner = runner or Runner()
    predict_fn = mlflow.trace(make_predict_fn(config, runner, render_enabled=render_enabled))
    scorers = build_scorers(agent_key, judge_endpoint=judge_endpoint)

    with mlflow.start_run(run_name=f"{agent_key}:{config.name}") as run:
        mlflow.set_tags({
            "agent_key": agent_key,
            "config_name": config.name,
            "content_hash": config.content_hash,
            "judge_endpoint": judge_endpoint,
            "repeats": str(repeats),
            "case_filter": ",".join(case_filter) if case_filter else "all",
        })
        result = mlflow.genai.evaluate(data=data, scorers=scorers, predict_fn=predict_fn)
        df = result.result_df

        names = [s.name for s in scorers]
        per_case: dict[str, list[str]] = defaultdict(list)
        outcomes: list[str] = []
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
