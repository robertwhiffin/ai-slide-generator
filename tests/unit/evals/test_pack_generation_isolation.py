"""I9: generate(out_dir=...) writes only where it is told; tests never rewrite the committed tree."""
import importlib

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)

from evals.harness import case

AGENTS = ["builder", "build_reviewer", "fixer", "fix_reviewer", "deck_reviewer", "architect", "data_analyst"]


def _stat(root):
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.mark.parametrize("agent", AGENTS)
def test_generate_into_out_dir_leaves_the_committed_tree_untouched(agent, tmp_path):
    mutations = importlib.import_module(f"evals.packs.{agent}.mutations")
    committed = case.PACKS_DIR / agent / "cases"
    before = _stat(committed)
    out = tmp_path / "cases"
    mutations.generate(out_dir=out)
    assert _stat(committed) == before, "generate(out_dir=tmp) wrote into the committed tree"
    written = sorted(d.name for d in out.iterdir() if d.is_dir())
    assert len(written) == 5
    loaded = case.load_cases(agent, root=out)
    assert sorted(c.case_id for c in loaded) == written
    one = case.load_case(agent, written[0], root=out)
    assert one.payload == case.load_case(agent, written[0]).payload


@pytest.mark.parametrize("agent", AGENTS)
def test_generate_default_targets_the_committed_tree(agent):
    import inspect

    mutations = importlib.import_module(f"evals.packs.{agent}.mutations")
    sig = inspect.signature(mutations.generate)
    assert sig.parameters["out_dir"].default is None
    assert mutations.CASES_DIR == case.PACKS_DIR / agent / "cases"


def test_load_case_root_defaults_to_the_committed_tree(tmp_path):
    assert case.load_cases("builder", root=tmp_path / "nope") == []
    assert {c.case_id for c in case.load_cases("builder")} == {
        d.name for d in (case.PACKS_DIR / "builder" / "cases").iterdir() if d.is_dir()
    }
