"""CLI: sweep an agent config through the eval harness, or calibrate the judge."""
from __future__ import annotations

import argparse
import os
import warnings

import src.core.database  # noqa: F401 - break import cycle before src.* imports

from evals.harness import auth, judge, mlflow_run
from evals.harness import render as render_mod
from evals.harness.case import meridian_section_css
from evals.harness.config import AgentEvalConfig, load_config, prices, v1_baseline
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS

HTML_ROLES = ("builder", "fixer")


def apply_profile(profile: str) -> str:
    return auth.apply_profile(profile)


def _endpoint_reachable(endpoint_name: str) -> bool:
    """Probe the serving endpoint; True if it resolves."""
    try:
        from databricks.sdk import WorkspaceClient

        WorkspaceClient().serving_endpoints.get(endpoint_name)
        return True
    except Exception:  # noqa: BLE001 - any failure means not reachable
        return False


def validate_endpoint(config: AgentEvalConfig) -> None:
    name = config.content.model.endpoint_name
    if name not in prices():
        warnings.warn(f"endpoint_name {name!r} has no entry in prices.yaml; cost will be unestimated",
                      UserWarning, stacklevel=2)
    if not _endpoint_reachable(name):
        raise SystemExit(f"endpoint_name {name!r} is not reachable (agent {config.agent_key})")


def _load(agent_key: str, config_arg: str) -> AgentEvalConfig:
    if config_arg == "v1-baseline":
        return v1_baseline(agent_key)
    cfg = load_config(config_arg)
    if cfg.agent_key != agent_key:
        raise SystemExit(f"--config is for agent {cfg.agent_key!r} but --agent is {agent_key!r}")
    return cfg


def _calibration_render_fn(case, candidate):
    return render_mod.render_slide(
        candidate.get("html", ""), candidate.get("scripts") or "", section_css=meridian_section_css())


def _print_trust_table(agent_key: str, rows: list[dict]) -> None:
    print(f"\n== judge calibration: {agent_key} ==")
    if not rows:
        print("(no cases in this pack yet; nothing to calibrate)")
        return
    print(f"{'case_id':<20}{'ref_passed':<12}{'mut_failed':<12}{'trusted':<9}reason")
    for r in rows:
        print(f"{r['case_id']:<20}{str(r['reference_passed']):<12}{str(r['mutation_failed']):<12}"
              f"{str(r['trusted']):<9}{r.get('reason', '')}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="run_eval")
    ap.add_argument("--agent", default="all", help="'all' or an agent key")
    ap.add_argument("--config", default="v1-baseline", help="path to a YAML config or 'v1-baseline'")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--judge-endpoint", default=judge.JUDGE_ENDPOINT)
    ap.add_argument("--cases", default=None, help="comma-separated case ids, e.g. 2,4")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--profile", default=auth.DEFAULT_PROFILE,
                    help="Databricks CLI profile every live call uses (overrides .env / shell "
                         "DATABRICKS_HOST); pass '' to keep the ambient env")
    args = ap.parse_args(argv)

    agents = list(GRAPH_V1_AGENT_KEYS) if args.agent == "all" else [args.agent]
    for a in agents:
        if a not in GRAPH_V1_AGENT_KEYS:
            raise SystemExit(f"unknown agent {a!r}; valid: {list(GRAPH_V1_AGENT_KEYS)}")

    if args.profile:
        # Before any model call: pin host/credentials so the .env's DATABRICKS_* cannot win.
        apply_profile(args.profile)

    if args.calibrate:
        for a in agents:
            rows = judge.calibrate(
                a, model=args.judge_endpoint,
                render_fn=_calibration_render_fn if a in HTML_ROLES else None)
            _print_trust_table(a, rows)
        return

    if args.agent == "all" and args.config != "v1-baseline":
        raise SystemExit("--agent all requires --config v1-baseline (a YAML config targets one agent)")
    case_filter = [c.strip() for c in args.cases.split(",") if c.strip()] if args.cases else None
    ran = 0
    for a in agents:
        cfg = _load(a, args.config)
        validate_endpoint(cfg)
        try:
            run_id = mlflow_run.run_sweep(
                cfg, agent_key=a, repeats=args.repeats, max_workers=args.max_workers,
                judge_endpoint=args.judge_endpoint, case_filter=case_filter,
                render_enabled=not args.no_render,
                tracking_uri=mlflow_run.default_tracking_uri())
        except mlflow_run.NoCasesError as e:
            print(f"{a}: skipped - {e}")
            continue
        ran += 1
        print(f"{a}: run_id={run_id}")
    if not ran:
        raise SystemExit(f"no cases to evaluate for {agents} (packs have no cases yet or --cases matched none)")


if __name__ == "__main__":
    main()
