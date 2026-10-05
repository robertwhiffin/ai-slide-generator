# Agent Configuration Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repo also has a required companion skill — load **executing-plans-tellr** (`.claude/skills/executing-plans-tellr/`) alongside it, per `CLAUDE.md`.

**Goal:** Build an offline harness that compares agent configurations (prompt + model) for the seven LangGraph roles against generated cases from a synthetic Meridian gold deck, scored by deterministic checks, render measurements, and a calibrated LLM judge, compared in the local MLflow UI, with promotion into the Graph Version 1 manifest.

**Architecture:** A shared core (`evals/harness/`) drives one configuration through the production `AgentRuntime.run_candidate` path, renders HTML outputs headless with Playwright, measures them, and scores every case with MLflow `genai.evaluate` scorers (deterministic + a `make_judge` LLM judge). Seven per-agent packs (`evals/packs/<agent>/`) each generate cases from the gold deck and carry their own judge prompt; they depend only on the core's file formats and interfaces, so they are built in parallel. A `promote.py` turns chosen configs into the frozen `agent_definition_manifest_v1.py` with updated pinned hashes.

**Tech Stack:** Python 3.11, MLflow 3.14 (`mlflow.genai.evaluate`, `make_judge`), Playwright 1.48 (chromium), PyYAML 6, pydantic v2, pytest. All already installed — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-02-agent-config-eval-harness-design.md`

## Global Constraints

- **No new dependencies.** MLflow 3.14, Playwright 1.48, PyYAML 6, pydantic v2 are already in `pyproject.toml` and `packages/databricks-tellr-app/pyproject.toml`. Do not add any.
- **Never `pip install` from an agent.** The Python env is a shared pyenv site-packages; installing corrupts parallel agents' runs (`CLAUDE.md`). If an import is missing, stop and report.
- **Harness lives under `evals/`, outside `src/` and `tests/`.** `testpaths = ["tests"]`, so `evals/` is never auto-collected. Harness *self-tests* live in `tests/unit/evals/` and run in CI with no model. Real-model runs live in `evals/` and are run only via `run_eval.py`, following the `tests/agentic` convention.
- **Use the production agent code unchanged.** Configurations run through `AgentRuntime.run_candidate(...)` and `PromptAssembler` — the same assembly, schema composition, and model adapter as production. Do not fork or reimplement prompt assembly.
- **All fixtures are synthetic and public-safe.** The Meridian brand is fake; the gold deck is the public HTML-vs-PowerPoint deck. No real brand content (Databricks design system) may enter the repo.
- **The judge model is pinned and configurable.** Default `databricks-claude-sonnet-5`, set as one constant in `evals/harness/judge.py`, overridable by `--judge-endpoint`. One judge endpoint across all compared configs; the comparison view must not mix endpoints.
- **Each agent is evaluated in isolation.** No whole-graph combinations. Design-system-on branch (Meridian) only; the default-style branch is out of scope.
- **Attribution.** End commit messages with `Co-authored-by: Isaac <no-reply@databricks.com>`. Do not push; do not merge to main. Work on branch `feat/eval-harness` off `feat/ws2a-ai-gateway`.

## Review Focus

- **Endpoint throttling (HTTP 429 / provider-unavailable) mid-sweep** — a reasonable person expects a throttled call to be retried and, if it still fails, excluded from the pass rate as `infra_error`, never counted as the agent failing. Pinned in **Task 3**.
- **A config naming an endpoint the workspace does not serve** — expect the CLI to fail fast before any model call, naming the offending field, not to burn a half-sweep then error. Pinned in **Task 7** (CLI endpoint validation).
- **The gold export's knit chrome leaking into a case fragment** — the downloaded deck wraps each slide in `slide-wrapper` / `slide-container` and carries a deck-level `<style>` block and Chart.js `<script>`s; a reasonable person expects each per-slide fixture to be the bare `<div class="slide">`/`<section class="slide">` fragment a builder emits, with no `<style>` and no wrapper. Pinned in **Task 1**.
- **Measuring a chart slide before Chart.js has rendered** — expect the renderer to wait for chart init (or a timeout) so an unfinished canvas is not mis-measured as overflow or a blank chart; a premature read is a false failure. Pinned in **Task 4**.
- **Promotion producing a non-byte-identical manifest, or silently breaking the v1 prompt-transition records** — expect promoting the current v1 to itself to yield an identical file and identical hashes, and expect a change to `data_analyst` or `build_reviewer` v1 prompt text (which `LegacyV1PromptTransition` keys on) to fail closed rather than corrupt the transition. Pinned in **Task 8**.

---

## File Structure

```
evals/
  __init__.py
  run_eval.py                         CLI entry point
  configs/
    prices.yaml                       per-endpoint token prices
    <agent>/<name>.yaml               one configuration (incl. v1-baseline is synthesised, not a file)
  fixtures/meridian/
    __init__.py
    bundle/                           Meridian design-system source (copied from ../generic-ds)
    meridian-ds.zip                   zipped bundle (copied from ../meridian-ds.zip)
    deck_spec.json                    the gold deck spec (from the .txt, structured)
    gold/<pos>.html                   gold deck, one bare slide fragment per position (0..9)
    gold/<pos>.js                     Chart.js init for chart slides (pos 3, 6), else absent
    resolved_style.txt               compiled Meridian style content (from a one-off import)
    section_css.txt                  token_css + template style block (deterministic_css)
  harness/
    __init__.py
    case.py                           Case dataclass + loader for packs/<agent>/cases/**
    config.py                         AgentEvalConfig: YAML -> DefinitionContent; v1-baseline
    runner.py                         run one config against one payload (thread-safe, retry)
    render.py                         Playwright render at 1280x720 + in-page measurements
    scorers.py                        contract, expected_category, render_measures scorers
    judge.py                          make_judge wrapper + calibration helper; JUDGE_ENDPOINT
    mlflow_run.py                     dataset build, genai.evaluate, tags/metrics, pass-rate agg
    promote.py                        chosen configs -> v1 manifest + pinned hashes
  packs/
    __init__.py
    <agent>/                          one per: architect data_analyst builder build_reviewer
      __init__.py                       fixer fix_reviewer deck_reviewer
      mutations.py                    generates cases/ from the gold deck
      judge_prompt.md                 this role's judge instructions
      cases/<case_id>/                generated: payload.json, reference.json, case.yaml
tests/unit/evals/
  __init__.py
  test_gold_split.py                  Task 1
  test_config_loader.py               Task 2
  test_runner.py                      Task 3
  test_render.py                      Task 4
  test_scorers.py                     Task 5
  test_judge.py                       Task 6
  test_mlflow_run.py                  Task 7
  test_promote.py                     Task 8
  test_pack_<agent>.py                Tasks 9-15 (mutation correctness, no model)
```

---

## Task 1: Scaffold, pytest path, and Meridian fixtures

**Files:**
- Create: `evals/__init__.py`, `evals/harness/__init__.py`, `evals/packs/__init__.py`, `evals/fixtures/meridian/__init__.py`
- Create: `evals/fixtures/meridian/bundle/**` (copy of `../generic-ds`), `evals/fixtures/meridian/meridian-ds.zip` (copy of `../meridian-ds.zip`)
- Create: `evals/fixtures/meridian/deck_spec.json`, `evals/fixtures/meridian/gold/<0..9>.html`, `evals/fixtures/meridian/gold/3.js`, `evals/fixtures/meridian/gold/6.js`, `evals/fixtures/meridian/resolved_style.txt`, `evals/fixtures/meridian/section_css.txt`
- Create: `evals/harness/case.py`, `tests/unit/evals/__init__.py`, `tests/unit/evals/test_gold_split.py`
- Create: `evals/fixtures/split_gold.py` (one-off splitter, kept for regeneration)
- Modify: `pyproject.toml` `[tool.pytest.ini_options]` — add `pythonpath = ["."]`

**Interfaces:**
- Produces: `evals/harness/case.py`
  - `@dataclass(frozen=True) class Case: case_id: str; agent_key: str; kind: Literal["positive","mutation"]; design_system_active: bool; fault: str; payload: dict; reference: dict; expect: dict`
  - `def load_case(agent_key: str, case_id: str) -> Case` — reads `evals/packs/<agent_key>/cases/<case_id>/{payload.json,reference.json,case.yaml}`
  - `def load_cases(agent_key: str) -> list[Case]` — all case dirs under a pack, sorted by `case_id`
  - `def gold_slide(position: int) -> str` — reads `evals/fixtures/meridian/gold/<position>.html`
  - `def gold_scripts(position: int) -> str` — reads `gold/<position>.js` or `""`
  - `def meridian_section_css() -> str` and `def meridian_resolved_style() -> str` — read the two `.txt` files
  - `def gold_deck_spec() -> dict` — reads `deck_spec.json`
  - `MERIDIAN_DESIGN_SYSTEM_ID` / `MERIDIAN_TEMPLATE_ID`: not needed by the harness (payloads carry CSS inline); omit.

- [ ] **Step 1: Copy the Meridian fixtures into the repo**

```bash
cd /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator
mkdir -p evals/fixtures/meridian/gold
cp -R ../generic-ds evals/fixtures/meridian/bundle
cp ../meridian-ds.zip evals/fixtures/meridian/meridian-ds.zip
touch evals/__init__.py evals/harness/__init__.py evals/packs/__init__.py evals/fixtures/meridian/__init__.py tests/unit/evals/__init__.py
```

- [ ] **Step 2: Produce `resolved_style.txt` and `section_css.txt` from a real import**

The payloads must carry the *same* `resolved_style` and `section_css` production would resolve, so capture them once from the real importer + resolver. Run this one-off and commit the two text files it writes (do not commit the sqlite db):

```python
# scratch: run from repo root, then delete the script
import src.core.database  # breaks the models import cycle (import FIRST)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import src.database.models  # noqa
from src.core.database import Base
from src.services.design_system_service import import_bundle
from src.services.template_sections import _extract_style_blocks_css
from src.database.models.design_system import DesignSystemTemplate

e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=e)
with Session(e) as s:
    ds = import_bundle(s, zip_bytes=open("evals/fixtures/meridian/meridian-ds.zip","rb").read(), user="eval")
    tpl = s.query(DesignSystemTemplate).filter_by(design_system_id=ds.id).first()
    style_block = _extract_style_blocks_css(tpl.layout_html)
    token_css = tpl.token_css or ""
    section_css = "\n\n".join(p for p in (token_css, style_block) if p)  # mirrors nodes._concat_css
    # resolved_style on the DS branch = compiled style content with type-scale markers stripped
    from src.services.design_system_compiler import strip_type_scale_region_markers
    resolved = strip_type_scale_region_markers(ds.compiled_style_content or "")
    open("evals/fixtures/meridian/resolved_style.txt","w").write(resolved)
    open("evals/fixtures/meridian/section_css.txt","w").write(section_css)
    print("resolved_style", len(resolved), "section_css", len(section_css))
```

Expected: both files non-empty; `section_css` contains `.slide {` and `--brand-core-primary`; `resolved_style` contains `SLIDE VISUAL STYLE`.

- [ ] **Step 3: Write `deck_spec.json` from the deck-spec text**

Transcribe `~/Downloads/test deck deck-spec.txt` into a structured JSON matching the architect's `DeckSpec` shape (title, audience, purpose, argument, call_to_action, narrative_arc[list], and `slides[]` each with position, purpose, content_brief, assumes, hands_off, data_references[]). The ten slide briefs are in the deck-spec text verbatim; `data_references` is `[]` for every slide except positions 3 and 6 which reference a conceptual chart (use `["device_render_comparison"]` and `["wcag_support_comparison"]` respectively). This is the architect's reference and the source of each builder brief.

- [ ] **Step 4: Write the gold splitter and split the deck**

Create `evals/fixtures/split_gold.py`. It reads `~/Downloads/html-slides-vs--powerpoint--a-better-way-to-present.html`, extracts each `<section class="slide ...">...</section>` (the ten slides, in `data-slide-index` order), and writes each as `gold/<pos>.html` **stripped of the `slide-wrapper`/`slide-container` chrome and with no `<style>` block** (builders emit a bare fragment). Chart slides (positions 3 and 6) carry a `<canvas>`; extract the matching per-canvas `<script>` IIFE into `gold/<pos>.js` and leave the canvas div in the HTML.

```python
import re, pathlib
SRC = pathlib.Path.home() / "Downloads/html-slides-vs--powerpoint--a-better-way-to-present.html"
OUT = pathlib.Path("evals/fixtures/meridian/gold")
html = SRC.read_text()
sections = re.findall(r'<div class="slide-container">\s*(<section.*?</section>)', html, re.S)
assert len(sections) == 10, f"expected 10 slides, got {len(sections)}"
scripts = re.findall(r'<script>\s*(\(function\(\).*?)</script>', html, re.S)  # the two canvas IIFEs
for pos, sec in enumerate(sections):
    assert "<style" not in sec.lower(), f"slide {pos} leaked a <style> block"
    assert "slide-wrapper" not in sec and "slide-container" not in sec
    (OUT / f"{pos}.html").write_text(sec.strip() + "\n")
# Map canvas id -> position; write per-canvas scripts to gold/<pos>.js
for sc in scripts:
    cid = re.search(r"Canvas:\s*(\w+)", sc)
    canvas_id = cid.group(1) if cid else None
    for pos, sec in enumerate(sections):
        if canvas_id and f'id="{canvas_id}"' in sec:
            (OUT / f"{pos}.js").write_text(sc.strip() + "\n")
print("wrote", len(sections), "slides,", len(scripts), "scripts")
```

- [ ] **Step 5: Write `evals/harness/case.py`** per the Interfaces block above. `load_case` reads the three files, validates `kind in {"positive","mutation"}`, and returns a frozen `Case`. `gold_slide`/`gold_scripts`/`meridian_section_css`/`meridian_resolved_style`/`gold_deck_spec` read the fixtures.

- [ ] **Step 6: Add `pythonpath` so self-tests can import the harness**

In `pyproject.toml` under `[tool.pytest.ini_options]`, add:

```toml
pythonpath = ["."]
```

- [ ] **Step 7: Write the failing test** `tests/unit/evals/test_gold_split.py`

```python
from evals.harness import case

def test_ten_gold_slides_are_bare_fragments_without_knit_chrome():
    for pos in range(10):
        html = case.gold_slide(pos)
        assert "<section" in html and 'class="slide' in html
        assert "<style" not in html.lower()        # deck CSS has a single writer
        assert "slide-wrapper" not in html and "slide-container" not in html

def test_chart_slides_carry_scripts_and_others_do_not():
    assert "new Chart" in case.gold_scripts(3)
    assert "new Chart" in case.gold_scripts(6)
    assert case.gold_scripts(0) == ""

def test_meridian_payload_pieces_are_present():
    assert ".slide {" in case.meridian_section_css()
    assert "--brand-core-primary" in case.meridian_section_css()
    assert "SLIDE VISUAL STYLE" in case.meridian_resolved_style()
    spec = case.gold_deck_spec()
    assert len(spec["slides"]) == 10
```

- [ ] **Step 8: Run the splitter, then the test**

Run: `python evals/fixtures/split_gold.py && python -m pytest tests/unit/evals/test_gold_split.py -v`
Expected: splitter writes 10 slides + 2 scripts; all three tests PASS.

- [ ] **Step 9: Commit**

```bash
git add evals/ tests/unit/evals/ pyproject.toml
git commit -m "feat(evals): scaffold eval harness, Meridian fixtures, gold deck split

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 2: Config loader and v1-baseline

**Files:**
- Create: `evals/harness/config.py`, `evals/configs/prices.yaml`, `evals/configs/builder/v1.yaml` (an example override file)
- Create/Modify: `tests/unit/evals/test_config_loader.py`

**Interfaces:**
- Consumes: `DefinitionContent`, `ModelConfiguration` from `src.services.graph_definition_manifest`; `load_graph_v1_manifest()`; `definition_content_hash()`.
- Produces: `evals/harness/config.py`
  - `@dataclass(frozen=True) class AgentEvalConfig: agent_key: str; name: str; content: DefinitionContent; content_hash: str`
  - `def load_config(path: str | Path) -> AgentEvalConfig` — read a YAML file; start from `base` (default `"v1"`, meaning the v1 definition for that `agent_key`), override `prompt_text` (inline or `prompt_file`), `endpoint_name`, `temperature`, `max_tokens`, `top_p`; rebuild `DefinitionContent`; compute `content_hash = definition_content_hash(content)`. The YAML's `agent_key` must match the base's.
  - `def v1_baseline(agent_key: str) -> AgentEvalConfig` — the unmodified v1 definition, `name="v1-baseline"`.
  - `class ConfigError(ValueError)` — raised with a message naming the offending field.
  - `def prices() -> dict[str, dict]` — parse `evals/configs/prices.yaml` → `{endpoint_name: {"input_per_1k": float, "output_per_1k": float}}`.

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_config_loader.py`

```python
import pytest
from evals.harness import config

def test_v1_baseline_matches_the_frozen_manifest():
    from src.services.graph_definition_manifest import load_graph_v1_manifest
    man = {d.agent_key: d for d in load_graph_v1_manifest().definitions}
    from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
    for key in GRAPH_V1_AGENT_KEYS:
        cfg = config.v1_baseline(key)
        assert cfg.name == "v1-baseline"
        assert cfg.content == man[key]
        from src.services.graph_definition_manifest import definition_content_hash
        assert cfg.content_hash == definition_content_hash(man[key])

def test_override_endpoint_and_prompt_rebuilds_content(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "agent_key: builder\nname: sonnet-test\n"
        "endpoint_name: databricks-claude-sonnet-5\nmax_tokens: 4096\n"
        "prompt_text: \"You are a slide builder. Build ONE slide.\"\n"
    )
    cfg = config.load_config(p)
    assert cfg.agent_key == "builder"
    assert cfg.content.model.endpoint_name == "databricks-claude-sonnet-5"
    assert cfg.content.model.max_tokens == 4096
    assert cfg.content.prompt_text.startswith("You are a slide builder")
    # hash moved away from baseline
    assert cfg.content_hash != config.v1_baseline("builder").content_hash

def test_unknown_agent_key_is_rejected_by_field_name(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("agent_key: wizard\nname: x\n")
    with pytest.raises(config.ConfigError) as e:
        config.load_config(p)
    assert "agent_key" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_config_loader.py -v`
Expected: FAIL (module `evals.harness.config` not found).

- [ ] **Step 3: Write `evals/harness/config.py`**

Load the base v1 `DefinitionContent` via `load_graph_v1_manifest()` keyed by `agent_key` (raise `ConfigError("agent_key ...")` for an unknown key — valid keys are `GRAPH_V1_AGENT_KEYS`). Apply overrides by `model_copy(update=...)` on the `DefinitionContent` and its nested `ModelConfiguration` (`content.model.model_copy(...)`). `prompt_file` is read relative to the YAML's directory. Leave `schema_overlay`, `assembly_rules`, `protected_assembly`, `schema_contract` as the base's (changing assembly rules is out of scope; `DefinitionContent`'s validator rejects assembly rules that do not match v1). Compute `content_hash` with `definition_content_hash`.

- [ ] **Step 4: Write `evals/configs/prices.yaml`** with the two endpoints in play and placeholder prices (documented as editable):

```yaml
# USD per 1,000 tokens. Edit to match current Databricks serving prices.
databricks-claude-opus-4-6:   { input_per_1k: 0.015, output_per_1k: 0.075 }
databricks-claude-sonnet-5:   { input_per_1k: 0.003, output_per_1k: 0.015 }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/evals/test_config_loader.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add evals/harness/config.py evals/configs/ tests/unit/evals/test_config_loader.py
git commit -m "feat(evals): config loader and v1-baseline

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 3: Runner (thread-safe, infra-error retry)

**Files:**
- Create: `evals/harness/runner.py`, `tests/unit/evals/test_runner.py`

**Interfaces:**
- Consumes: `AgentEvalConfig` (Task 2); `AgentRuntime`, `DatabricksModelAdapter`, `AgentAssemblyContext`, `RunObservation`, `CandidateRunOutcome`, `classify_test_run_failure`, `ModelProviderUnavailableError`, `PinnedInvocationEndpointError` from `src.services.agent_runtime`.
- Produces: `evals/harness/runner.py`
  - `@dataclass(frozen=True) class RunResult: status: str; structured: dict | None; raw: dict | None; prompt: str | None; latency_ms: float | None; input_tokens: int | None; output_tokens: int | None; error_detail: str | None; infra_error: bool`
  - `class Runner:` constructs its OWN `AgentRuntime` (never `get_agent_runtime`/`get_agent_test_runtime`), with a stub loader and a `DatabricksModelAdapter(transport_options={"timeout": 120.0, "max_retries": 0})`.
    - `def __init__(self, *, model_adapter=None, max_infra_retries: int = 3)` — `model_adapter` injectable for tests.
    - `def run(self, config: AgentEvalConfig, payload: dict, *, design_system_active: bool) -> RunResult` — calls `self._runtime.run_candidate(config.agent_key, config.content, config.content_hash, payload, AgentAssemblyContext(design_system_active), observation=obs)`. Retries only when the outcome is an infra error (status `model_error` with `endpoint_unavailable:`/`unexpected_error:` from a provider exception) with exponential backoff; after `max_infra_retries` returns `RunResult(infra_error=True, ...)`. A `contract` failure (status `incomplete`) is a real failure, returned as-is, not retried.
  - `def _is_infra_error(outcome: CandidateRunOutcome) -> bool` — status is `model_error` and `error_detail` starts with `endpoint_unavailable:` or `unexpected_error:`.
  - A module-level stub loader class whose `.resolve()` raises `AssertionError` (the runner must never resolve a release).

**Note on the caller-restriction test:** `tests/unit/test_agent_runtime.py::test_run_candidate_is_reachable_only_from_the_agent_test_workbench` scans only `src/` (verified: `_src_python_files` globs `src/**/*.py`). The harness lives under `evals/`, so it does not trip this test and no test change is needed. For honesty, update the `run_candidate` docstring in `src/services/agent_runtime.py` (currently "Only the #267 test workbench may call this (spec §7.1)") to add: "and the offline eval harness (`evals/harness/runner.py`)." This is a comment-only edit; commit it with Step 5.

**Note on thread safety:** `run_candidate` builds a fresh `ResolvedDefinition` per call and uses a pass-through identity sink, so no shared mutable state is written. `PromptAssembler` and `AgentSchemaRegistry` are read-only after construction. The concurrency test below is the proof; if it reveals shared state, construct one `Runner` per worker thread in `mlflow_run.py` (Task 7) instead of sharing one.

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_runner.py`

```python
import threading
from concurrent.futures import ThreadPoolExecutor
from evals.harness import config, runner

class _StubAdapter:
    """Returns a valid structured output per role without a network call."""
    def __init__(self): self.calls = 0; self._lock = threading.Lock()
    def invoke(self, *, agent_key, configuration, schema, prompt):
        with self._lock: self.calls += 1
        return _valid_output_for(schema)   # build a minimal valid instance of the schema

def _valid_output_for(schema):
    from src.domain.skill_io import BuilderOutput
    if schema.__name__.startswith("Builder") or issubclass(schema, BuilderOutput):
        return schema(position=1, html="<section class='slide'><h1>x</h1></section>", scripts="")
    raise AssertionError(f"add a builder for {schema.__name__}")

def test_runner_returns_structured_output_for_a_builder_config():
    r = runner.Runner(model_adapter=_StubAdapter())
    cfg = config.v1_baseline("builder")
    payload = {"position": 1, "slide_spec": {"position": 1, "title": "t", "purpose": "p"},
               "assumes": [], "hands_off": [], "resolved_data": {"synthesis":"","figures":[],"gaps":[]},
               "section_html": "", "section_css": ".slide{}", "resolved_style": "x",
               "design_system_active": True}
    res = r.run(cfg, payload, design_system_active=True)
    assert res.status == "completed"
    assert "slide" in res.structured["html"]
    assert res.infra_error is False

def test_concurrent_runs_do_not_interfere():
    r = runner.Runner(model_adapter=_StubAdapter())
    cfg = config.v1_baseline("builder")
    payload = {...}  # as above
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: r.run(cfg, payload, design_system_active=True), range(32)))
    assert all(x.status == "completed" for x in results)

def test_persistent_provider_failure_is_marked_infra_error_not_counted():
    class Boom:
        def invoke(self, **k):
            from src.services.agent_runtime import ModelProviderUnavailableError
            raise ModelProviderUnavailableError("429 throttled")
    r = runner.Runner(model_adapter=Boom(), max_infra_retries=1)
    res = r.run(config.v1_baseline("builder"), {...}, design_system_active=True)
    assert res.infra_error is True
    assert res.status != "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_runner.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `evals/harness/runner.py`** per the Interfaces block. Fill the `payload = {...}` placeholders in the test with the builder payload from Step 1's first test.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/evals/test_runner.py -v`
Expected: PASS, including the 32-way concurrency test and the infra-error test.

- [ ] **Step 5: Commit**

```bash
git add evals/harness/runner.py tests/unit/evals/test_runner.py
git commit -m "feat(evals): thread-safe runner over run_candidate with infra-error retry

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 4: Renderer and in-page measurements

**Files:**
- Create: `evals/harness/render.py`, `tests/unit/evals/test_render.py`

**Interfaces:**
- Consumes: `playwright.sync_api.sync_playwright`; `case.meridian_section_css()`.
- Produces: `evals/harness/render.py`
  - `@dataclass(frozen=True) class RenderMeasures: overflow_px: float; min_contrast: float; off_palette: tuple[str, ...]; console_errors: tuple[str, ...]; rendered: bool`
  - `def palette_hexes(section_css: str) -> set[str]` — parse every `#rrggbb`/`#rgb` and `rgb(...)` from the token CSS, normalise to lowercase 6-digit hex; include `#ffffff`, `#000000`, and treat `transparent`/`rgba(...,0)` as allowed.
  - `def render_slide(html: str, scripts: str = "", *, section_css: str, width: int = 1280, height: int = 720, chart_timeout_ms: int = 4000) -> RenderMeasures` — build a full HTML doc: `<style>` = `section_css`; a `.slide` sized `width`x`height`; inject the fragment; add the Chart.js CDN `<script>` then the slide `scripts`. Launch chromium headless, set viewport, `wait_for_load_state("networkidle")`, then **if the fragment contains `<canvas`, poll until for every `<canvas>` `canvas.width > 0 AND canvas.height > 0` AND `window.Chart` is defined, OR `chart_timeout_ms` elapses. On timeout, measure as-is and append `"chart-init-timeout"` to `console_errors`, so a never-initialised chart surfaces as a failure rather than passing silently.** Collect `console` error events. Evaluate in-page JS returning:
    - `overflow_px`: `max(0, scrollHeight - height, scrollWidth - width)` measured on the `.slide` element.
    - `min_contrast`: minimum WCAG contrast ratio over text-bearing elements (computed from `getComputedStyle` color vs effective background; standard luminance formula).
    - `off_palette`: computed `color`/`background-color` values (as hex) used by elements that are not in `palette_hexes(section_css)`.
  - On a page crash or load failure return `RenderMeasures(rendered=False, console_errors=(...,))` with other fields at sentinel values (`overflow_px=0.0`, `min_contrast=0.0`, `off_palette=()`).

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_render.py`

```python
from evals.harness import render, case

CSS = case.meridian_section_css()

def test_gold_bullet_slide_fits_and_is_on_palette():
    m = render.render_slide(case.gold_slide(1), section_css=CSS)
    assert m.rendered is True
    assert m.overflow_px == 0
    assert m.off_palette == ()

def test_gold_chart_slide_waits_for_chartjs_and_fits():
    m = render.render_slide(case.gold_slide(3), case.gold_scripts(3), section_css=CSS)
    assert m.rendered is True
    assert m.overflow_px == 0
    assert m.console_errors == ()

def test_overflowing_slide_is_measured_dirty():
    bloated = case.gold_slide(1).replace("</ul>", "<li>x</li>"*60 + "</ul>")
    m = render.render_slide(bloated, section_css=CSS)
    assert m.overflow_px > 0

def test_off_palette_colour_is_flagged():
    rogue = case.gold_slide(1).replace('class="slide-title"', 'class="slide-title" style="color:#E11D48"')
    m = render.render_slide(rogue, section_css=CSS)
    assert any("e11d48" in c for c in m.off_palette)

def test_low_contrast_text_lowers_min_contrast():
    pale = case.gold_slide(1).replace('class="slide-subtitle"', 'class="slide-subtitle" style="color:#f0f0f0"')
    m = render.render_slide(pale, section_css=CSS)
    assert m.min_contrast < 4.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_render.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `evals/harness/render.py`** per Interfaces. Use `sync_playwright` with `chromium.launch(headless=True)`; reuse one browser per `render_slide` call for simplicity (optimise later only if needed). The in-page measurement script is the substantive part — write it to walk visible text elements, compute contrast against the nearest non-transparent background, and collect used colours.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/evals/test_render.py -v`
Expected: PASS. (Chromium is installed locally; verified.)

- [ ] **Step 5: Commit**

```bash
git add evals/harness/render.py tests/unit/evals/test_render.py
git commit -m "feat(evals): headless render with overflow, contrast and palette measurements

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 5: Shared scorers

**Files:**
- Create: `evals/harness/scorers.py`, `tests/unit/evals/test_scorers.py`

**Interfaces:**
- Consumes: `RenderMeasures` (Task 4); `src.domain.skill_io` output schemas; `src.domain.finding.CRITERIA`.
- Produces: `evals/harness/scorers.py` — plain functions (wrapped as MLflow scorers in Task 7), each returning `(passed: bool, rationale: str)`:
  - `def contract_score(structured: dict | None) -> tuple[bool, str]` — pass iff `structured is not None` (the runtime already validated the schema; `None` means contract failure).
  - `def expected_category_score(agent_key: str, structured: dict, expect: dict) -> tuple[bool, str]` — role-dispatched:
    - architect: `structured["intent"] == expect["intent"]`; for `edit`, `set(structured["target_positions"]) == set(expect["positions"])`.
    - data_analyst: `structured["outcome"] == expect["outcome"]`.
    - build_reviewer / fix_reviewer / deck_reviewer: let `got = {(f["criterion"], f["slide_index"]) for f in structured["findings"]}`; `objective_got = {c for (c,_) in got if CRITERIA[c].objective}` (guarding unknown criteria as a fail). Pass iff every `(criterion, position)` in `expect["criteria"]`×`expect["positions"]` is present AND no objective criterion outside `expect["criteria"]` appears. For fix_reviewer accept/reject cases, also check `structured["verdict"]` against `expect["verdict"]` when present.
  - `def render_measures_score(measures: RenderMeasures, html: str) -> tuple[bool, str]` — pass iff `measures.rendered` and `overflow_px == 0` and `min_contrast >= 4.5` and `off_palette == ()` and `console_errors == ()` and `"<style" not in html.lower()`.

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_scorers.py`

```python
from evals.harness import scorers, render

def test_contract_fails_on_none():
    assert scorers.contract_score(None)[0] is False
    assert scorers.contract_score({"html": "x"})[0] is True

def test_expected_category_reviewer_exact_match():
    out = {"findings": [{"criterion": "rogue_colour", "slide_index": 2, "objective": True}], "verdict": "surfaced"}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is True

def test_expected_category_reviewer_extra_objective_finding_fails():
    out = {"findings": [
        {"criterion": "rogue_colour", "slide_index": 2, "objective": True},
        {"criterion": "overflow", "slide_index": 2, "objective": True}]}
    assert scorers.expected_category_score("build_reviewer", out, {"criteria": ["rogue_colour"], "positions": [2]})[0] is False

def test_expected_category_reviewer_missing_planted_criterion_fails():
    assert scorers.expected_category_score("build_reviewer", {"findings": []}, {"criteria": ["overflow"], "positions": [3]})[0] is False

def test_architect_intent_match():
    assert scorers.expected_category_score("architect", {"intent": "build", "target_positions": []}, {"intent": "build"})[0] is True
    assert scorers.expected_category_score("architect", {"intent": "edit", "target_positions": [2,3]}, {"intent": "edit", "positions": [3,2]})[0] is True

def test_render_measures_rejects_style_tag_and_overflow():
    clean = render.RenderMeasures(0, 7.0, (), (), True)
    assert scorers.render_measures_score(clean, "<section class='slide'></section>")[0] is True
    assert scorers.render_measures_score(clean, "<style>x</style>")[0] is False
    dirty = render.RenderMeasures(120, 7.0, (), (), True)
    assert scorers.render_measures_score(dirty, "<section></section>")[0] is False
    nil_render = render.RenderMeasures(0, 7.0, (), (), False)
    assert scorers.render_measures_score(nil_render, "<section class='slide'></section>")[0] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_scorers.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `evals/harness/scorers.py`** per Interfaces. Guard `CRITERIA[c]` with a membership check so an unknown criterion name scores as a fail with a clear rationale.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/evals/test_scorers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/harness/scorers.py tests/unit/evals/test_scorers.py
git commit -m "feat(evals): deterministic scorers (contract, expected_category, render_measures)

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 6: Judge wrapper and calibration helper

**Files:**
- Create: `evals/harness/judge.py`, `tests/unit/evals/test_judge.py`

**Interfaces:**
- Consumes: `mlflow.genai.make_judge`; pack `judge_prompt.md` files; `Case` (Task 1); `RunResult` (Task 3); `RenderMeasures` (Task 4).
- Produces: `evals/harness/judge.py`
  - `JUDGE_ENDPOINT = "databricks-claude-sonnet-5"` — the single pinned default.
  - `def judge_prompt(agent_key: str) -> str` — reads `evals/packs/<agent_key>/judge_prompt.md`.
  - `def build_judge(agent_key: str, *, model: str = JUDGE_ENDPOINT)` — `make_judge(name=f"{agent_key}_equivalence", instructions=judge_prompt(agent_key), model=f"databricks:/{model}", feedback_value_type=...)`. The judge instructions template references `{{ outputs }}` and `{{ expectations }}` (MLflow judge template vars); the harness supplies `expectations` = reference + render measures and `outputs` = candidate output.
  - `def judge_payload(case, result, measures) -> dict` — assembles the dict passed to the judge: `{"candidate": result.structured, "reference": case.reference, "brief_or_finding": case.payload-derived context, "measures": measures-as-dict}`. `brief_or_finding` by role: builder → the `slide_spec` dict; fixer / build_reviewer / fix_reviewer → the `finding` dict; architect → the user `message` plus `current_deck_spec`; data_analyst → the `data_request`; deck_reviewer → `narrative_arc` plus `call_to_action`.
  - `def calibrate(agent_key: str, *, model: str = JUDGE_ENDPOINT) -> list[dict]` — for each case in the pack, run the judge twice: once with the **reference as the candidate** (must pass) and once with the **mutated/unfixed input as the candidate** (must fail). Returns per-case `{case_id, reference_passed: bool, mutation_failed: bool, trusted: bool}`. A pack is trusted iff every case's `trusted` is True.

**Testing note:** the judge itself needs a model, so the unit test mocks `make_judge`. The real calibration runs via `run_eval.py --calibrate` (Task 7/8), not in CI.

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_judge.py` (mocks the model)

```python
from unittest.mock import patch, MagicMock
from evals.harness import judge

def test_default_endpoint_is_sonnet():
    assert judge.JUDGE_ENDPOINT == "databricks-claude-sonnet-5"

def test_build_judge_uses_pinned_model_and_pack_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "judge_prompt", lambda k: "Judge {{ outputs }} vs {{ expectations }}")
    with patch("evals.harness.judge.make_judge") as mj:
        judge.build_judge("builder")
        _, kw = mj.call_args
        assert kw["model"] == "databricks:/databricks-claude-sonnet-5"
        assert "builder" in kw["name"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_judge.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `evals/harness/judge.py`** per Interfaces. `calibrate` depends on pack cases existing; it is exercised live in Tasks 9-15, not in this unit test.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/evals/test_judge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/harness/judge.py tests/unit/evals/test_judge.py
git commit -m "feat(evals): make_judge wrapper (Sonnet default) and calibration helper

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 7: MLflow run assembly and CLI

**Files:**
- Create: `evals/harness/mlflow_run.py`, `evals/run_eval.py`, `tests/unit/evals/test_mlflow_run.py`

**Interfaces:**
- Consumes: everything above; `mlflow`, `mlflow.genai.evaluate`, `mlflow.genai.scorers.scorer`, `mlflow.entities.Feedback`; `MLFLOW_GENAI_EVAL_MAX_WORKERS`.
- Produces: `evals/harness/mlflow_run.py`
  - `def build_dataset(cases: list[Case], repeats: int) -> list[dict]` — `repeats` rows per case: `{"inputs": {"agent_key", "case_id", "repeat"}, "expectations": {"expect": case.expect, "reference": case.reference, "design_system_active": case.design_system_active}}`.
  - `def make_predict_fn(config, runner, *, render_enabled: bool) -> Callable` — closure `predict_fn(agent_key, case_id, repeat)`: load the case, run `runner.run(config, case.payload, design_system_active=...)`, render if `render_enabled` and the role emits HTML (builder/fixer), return `{"structured", "raw", "render", "latency_ms", "input_tokens", "output_tokens", "status", "infra_error"}`. `render` is a `RenderMeasures`-as-dict for builder/fixer and `None` for architect, data_analyst, build_reviewer, fix_reviewer, deck_reviewer (no HTML to render); the `render_measures` scorer runs only for builder/fixer and skips a `None` render.
  - Scorers (MLflow `@scorer`): `contract`, `expected_category` (deterministic roles), `render_measures` (builder/fixer), `judge` (via Task 6). Each reads `outputs` + `expectations`, returns `Feedback(value="pass"/"fail"/"skip", rationale=...)`. An `infra_error` prediction scores `"skip"` on every scorer. The `judge` scorer: a judge-model call that fails or returns an unparseable verdict is a `judge_error` → the scorer returns `Feedback(value="skip", ...)`; it is NOT retried (unlike the runner's infra retry) and is NOT counted as pass or fail. A judge endpoint unavailable for the whole sweep surfaces as every judge row = skip, and `run_sweep` tags the run `judge_unavailable`.
  - `def run_sweep(config, *, agent_key, repeats, max_workers, judge_endpoint, case_filter=None, render_enabled=True) -> str` — set `MLFLOW_GENAI_EVAL_MAX_WORKERS`, tracking URI `sqlite:///mlflow.db`, start a run tagged `agent_key`, `config_name`, `content_hash`, `judge_endpoint`, `repeats`, `case_filter`; call `genai.evaluate(data=..., scorers=..., predict_fn=...)`; log aggregate metrics: overall pass rate (over non-skip rows), per-case pass rate, repeat stddev, infra_error / judge_error counts, mean/p95 latency, mean tokens, estimated cost from `prices()`. Aggregates are logged as MLflow metrics via `mlflow.log_metric` (`pass_rate`, per-case `pass_rate`, `repeat_stddev`, `infra_error_count`, `judge_error_count`, `mean_latency_ms`, `p95_latency_ms`, `mean_input_tokens`, `mean_output_tokens`, `est_cost_usd`); config identity (`config_name`, `content_hash`, `judge_endpoint`, `repeats`) is logged as tags. Tag `not_comparable` if infra rate > 10%. Returns the MLflow run id.
- Produces: `evals/run_eval.py` — argparse CLI: `--agent {all,<key>}`, `--config <path|v1-baseline>`, `--repeats 3`, `--max-workers 8`, `--judge-endpoint`, `--cases 2,4`, `--calibrate`, `--no-render`. `--agent all` sweeps every pack. `--calibrate` calls `judge.calibrate` per pack and prints a trust table instead of sweeping.
  - `def _endpoint_reachable(endpoint_name: str) -> bool` — a reachability probe mirroring `tests/agentic/gates.py` (query the serving endpoint; True if it resolves).
  - `def validate_endpoint(config: AgentEvalConfig) -> None` — Called once per config immediately after loading it and BEFORE `run_sweep` (before any worker pool or model call). If `config.content.model.endpoint_name` is not in `prices()` emit a warning (not fatal). If `not _endpoint_reachable(...)`, `raise SystemExit("endpoint_name ... is not reachable")`. This is the fail-fast gate from Review Focus.

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_mlflow_run.py` (no model; stub predict + judge)

```python
from evals.harness import mlflow_run
from evals.harness.case import Case

def _case(cid, expect, kind="mutation"):
    return Case(cid, "build_reviewer", kind, True, "fault", payload={}, reference={}, expect=expect)

def test_build_dataset_expands_repeats():
    rows = mlflow_run.build_dataset([_case("a", {"criteria": ["overflow"], "positions": [3]})], repeats=3)
    assert len(rows) == 3
    assert {r["inputs"]["repeat"] for r in rows} == {0, 1, 2}
    assert rows[0]["inputs"]["case_id"] == "a"

def test_pass_rate_excludes_infra_rows():
    # given per-row scorer values, the aggregation counts pass/(pass+fail), skip excluded
    agg = mlflow_run.pass_rate(["pass", "pass", "fail", "skip"])
    assert agg == 2/3

def test_unservable_endpoint_fails_fast_naming_the_field(monkeypatch):
    import evals.run_eval as cli
    from evals.harness import config
    cfg = config.v1_baseline("builder").content.model_copy(
        update={"model": config.v1_baseline("builder").content.model.model_copy(
            update={"endpoint_name": "no-such-endpoint"})})
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: False)
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.validate_endpoint(config.AgentEvalConfig("builder", "x", cfg, "h"))
    assert "endpoint_name" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_mlflow_run.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `evals/harness/mlflow_run.py` and `evals/run_eval.py`** per Interfaces. Factor `pass_rate(values: list[str]) -> float` as a pure helper so it is unit-testable without MLflow. Wrap the deterministic scorer functions from Task 5 and the judge from Task 6 as `@scorer`-decorated callables.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/evals/test_mlflow_run.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke-check the CLI wiring with a stub model (no network)**

Run: `python -m pytest tests/unit/evals/test_mlflow_run.py -v` (covered). Defer the live sweep to Task 16.

- [ ] **Step 6: Commit**

```bash
git add evals/harness/mlflow_run.py evals/run_eval.py tests/unit/evals/test_mlflow_run.py
git commit -m "feat(evals): MLflow genai.evaluate assembly and run_eval CLI

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Task 8: Promotion to Graph Version 1

**Files:**
- Create: `evals/harness/promote.py`, `tests/unit/evals/test_promote.py`

**Interfaces:**
- Consumes: `AgentEvalConfig` (Task 2); `load_graph_v1_manifest`, `GraphV1Manifest`, `definition_content_hash`, `GRAPH_V1_AGENT_KEYS` from `src.services.graph_definition_manifest`; `_transition_records` from `src.services.prompt_assembler`.
- Produces: `evals/harness/promote.py`
  - `def promote(chosen: dict[str, AgentEvalConfig], *, dry_run: bool = False) -> dict` — for every role in `GRAPH_V1_AGENT_KEYS`, take `chosen[role].content` if present else the current v1 definition; build a `GraphV1Manifest`; call `assert_complete(GRAPH_V1_AGENT_KEYS)`; serialise exactly as the frozen file does and rewrite `GRAPH_VERSION_1_MANIFEST_JSON`; recompute each role's `definition_content_hash` and rewrite both pinned tables. Returns `{role: new_hash}`.
  - **Serialisation (verified byte-exact):** the manifest literal is `json.dumps(json.loads(J), indent=2, ensure_ascii=False)` and the file body is exactly `'"""Generated Graph Version 1 Agent Definition snapshot. Do not edit by hand."""\n\nGRAPH_VERSION_1_MANIFEST_JSON = ' + repr(new_json) + '\n'`.
  - **Pinned-hash sites** (update the `PACKAGED_V1_CONTENT_HASHES` dict in both): `tests/unit/test_packaged_release_loader.py` and `tests/unit/test_graph_definition_manifest.py`. Do NOT touch `V1_SCHEMA_CONTRACT_DIGESTS` / `V2_SCHEMA_CONTRACT_DIGESTS` (the output schema is unchanged).
  - **Transition guard:** promote ALWAYS raises `PromoteBlocked` naming the role when `chosen` changes `prompt_text` for `data_analyst` or `build_reviewer`. Their v1 prompt is the `source_composite_prompt` of a `LegacyV1PromptTransition` wired to the live `src/core/skills/<role>.py` INSTRUCTIONS import; changing it would move the migration's source text and silently stop existing installs that hold the genuine old prompt from migrating. Changing those two roles' prompts is a separate, deliberate migration (as the fix-reviewer change was done by hand) and is out of this harness's scope.
  - `class PromoteBlocked(RuntimeError)`.
  - **Bootstrap-guard note (no action, confirm only):** the `graph_configuration_bootstrap` integrity guard runs only on *first* install (it inserts the complete v1 and compares; it is skipped when a release already exists). So promoting a new manifest does not retroactively break an already-bootstrapped database. A *fresh* bootstrap after promote seeds the new definitions and compares their hashes against the same manifest, so they match; `REQUIRED_SMOKE_PAYLOADS` are test cases unaffected by a prompt change. Devloop forks re-fork from prod on each deploy. No guard change is needed; confirm this still holds when running Step 4.

- [ ] **Step 1: Write the failing test** `tests/unit/evals/test_promote.py`

```python
from evals.harness import promote
from evals.harness import config

def test_promoting_v1_to_itself_is_a_no_op(tmp_path, monkeypatch):
    # dry_run returns the current hashes unchanged; the serialised file equals the current file
    import src.services.agent_definition_manifest_v1 as m
    before = open(m.__file__).read()
    result = promote.promote({}, dry_run=True)
    from src.services.graph_definition_manifest import load_graph_v1_manifest, definition_content_hash
    current = {d.agent_key: definition_content_hash(d) for d in load_graph_v1_manifest().definitions}
    assert result == current
    assert open(m.__file__).read() == before   # dry run wrote nothing

def test_changing_data_analyst_prompt_is_blocked_by_default():
    cfg = config.v1_baseline("data_analyst")
    changed = config.AgentEvalConfig("data_analyst", "x",
        cfg.content.model_copy(update={"prompt_text": cfg.content.prompt_text + "\n\nEXTRA"}),
        "ignored")
    import pytest
    with pytest.raises(promote.PromoteBlocked) as e:
        promote.promote({"data_analyst": changed})
    assert "data_analyst" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/evals/test_promote.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `evals/harness/promote.py`** per Interfaces, with `dry_run` returning hashes without writing.

- [ ] **Step 4: Run test to verify it passes, then prove round-trip identity against the real suite**

Run: `python -m pytest tests/unit/evals/test_promote.py -v`
Then prove a real promote-to-self leaves the pinned-hash suite green:
Run: `python -c "import src.core.database; from evals.harness import promote; promote.promote({})" && python -m pytest tests/unit/test_packaged_release_loader.py tests/unit/test_graph_definition_manifest.py tests/unit/test_graph_configuration_bootstrap.py -q && git diff --stat`
Expected: both suites PASS and `git diff --stat` shows no changes (promote-to-self is byte-identical). Discard any change with `git checkout -- .` if the diff is non-empty — a non-empty diff is a serialisation bug to fix before proceeding.

- [ ] **Step 5: Commit**

```bash
git add evals/harness/promote.py tests/unit/evals/test_promote.py
git commit -m "feat(evals): promote chosen configs into Graph Version 1 manifest + hashes

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Tasks 9-15: Agent packs (parallel)

Each pack is independent and depends only on the core (Tasks 1-7). Build the seven in parallel. Every pack follows the SAME shape; the per-agent specifics are in the table at the end of each task.

**Common pack structure** (`evals/packs/<agent>/`):
- `__init__.py`
- `mutations.py` — `def generate() -> None` writes `cases/<case_id>/{payload.json,reference.json,case.yaml}` for the 5 cases, deriving every value from the gold deck via `evals.harness.case`. Running it is idempotent.
- `judge_prompt.md` — judge instructions with `{{ outputs }}` and `{{ expectations }}` template vars; must instruct a pass/fail verdict BEFORE rationale; always references the reference and (for builder/fixer) the render measures.
- `cases/**` — generated, committed.
- Self-test `tests/unit/evals/test_pack_<agent>.py` — asserts each mutation planted exactly its fault (by diffing against the gold or by render, no model), and that `expected_category_score` of the reference against its own `expect` passes (the reference is a valid positive).

**Positions are 0-indexed throughout**, matching `gold/<pos>.html` and `SlideSpec.position`. Where this plan writes 'gold slide N' it means position N (0-indexed); the deck-spec text's 'Slide 1..10' is 1-indexed, mapping as position = spec_number − 1 (so deck-spec 'Slide 9' = position 8 = objections; 'Slide 10' = position 9 = verdict).

**`reference.json` schema by role:** builder/fixer → `{\"html\": str, \"scripts\": str}`; build_reviewer/fix_reviewer → `{\"findings\": [Finding], \"verdict\": str}`; deck_reviewer → `{\"findings\": [Finding]}`; architect → `{\"intent\": str, \"deck_spec\": object|null, \"target_positions\": [int]}`; data_analyst → `{\"outcome\": str, \"synthesis\": str|null}`.

**Payloads carry only the keys a case exercises.** `model_payload_for` (called inside `run_candidate`) projects the payload onto the role's `MODEL_PAYLOAD_KEYS` and drops the rest, so e.g. a builder payload may omit `corrective_instruction` (a retry-only key) without error.

**Payload construction:** build each role's payload with the exact keys the role is shown, taken from `MODEL_PAYLOAD_KEYS[<role>]` in `src.services.agent_model_payload`, filling `section_css`/`resolved_style` from `case.meridian_section_css()`/`meridian_resolved_style()` and `design_system_active=True`.

### Task 9: builder pack

**Files:** Create `evals/packs/builder/{__init__.py,mutations.py,judge_prompt.md}`, generated `cases/**`, `tests/unit/evals/test_pack_builder.py`.

**Cases (payload = builder MODEL_PAYLOAD_KEYS: position, slide_spec, assumes, hands_off, resolved_data, section_html, section_css, resolved_style, design_system_active):**

| case_id | kind | derivation | reference / expect |
|---|---|---|---|
| `gold_bullets` | positive | brief for gold slide 1 (The Problem) | reference = `gold_slide(1)`; expect: builds a slide delivering the hand-off, Meridian classes, no `<style>`, fits, on-palette |
| `gold_chart` | positive | brief for gold slide 3 (responsive), `resolved_data` carries the device-render figures | reference = `gold_slide(3)` + `gold_scripts(3)`; expect as above incl. a working chart |
| `gold_stats` | positive | brief for gold slide 9 (verdict scorecard) | reference = `gold_slide(9)`; expect: three stat cards, fits |
| `too_much_content` | mutation | slide 1 brief but `content_brief` demands ~12 dense bullets | reference = a correctly condensed slide; judge: does the builder keep it inside the frame (degrade sensibly) rather than overflow |
| `chart_no_data` | mutation | slide 3 brief with `resolved_data` emptied (`figures: []`) | reference = a slide that states the point without inventing figures; judge: builds without fabricating a chart/numbers |

**judge_prompt.md:** "Given the slide BRIEF and the render MEASURES, and a REFERENCE slide that is known good, decide whether the CANDIDATE delivers the brief's hand-off at least as well as the reference. The candidate need not match the reference's wording or layout. Fail if it omits the hand-off, invents data not in resolved_data, or overflows. Answer PASS or FAIL first, then one sentence."

- [ ] **Step 1:** Write `mutations.py::generate()` producing the 5 case dirs from the gold.
- [ ] **Step 2:** Run `python -m evals.packs.builder.mutations` (via a tiny `if __name__` guard) to generate cases.
- [ ] **Step 3:** Write `judge_prompt.md`.
- [ ] **Step 4: Write the failing self-test** `tests/unit/evals/test_pack_builder.py`:

```python
from evals.harness import case, render
def test_cases_generated():
    cases = case.load_cases("builder")
    assert {c.case_id for c in cases} == {"gold_bullets","gold_chart","gold_stats","too_much_content","chart_no_data"}
def test_chart_no_data_payload_has_empty_figures():
    c = case.load_case("builder", "chart_no_data")
    assert c.payload["resolved_data"]["figures"] == []
def test_reference_slides_render_clean():
    for cid in ("gold_bullets","gold_chart","gold_stats"):
        c = case.load_case("builder", cid)
        m = render.render_slide(c.reference["html"], c.reference.get("scripts",""), section_css=case.meridian_section_css())
        assert m.overflow_px == 0 and m.off_palette == ()
```

- [ ] **Step 5:** Run `python -m pytest tests/unit/evals/test_pack_builder.py -v` → PASS.
- [ ] **Step 6: Commit** `git add evals/packs/builder tests/unit/evals/test_pack_builder.py && git commit -m "feat(evals): builder pack

Co-authored-by: Isaac <no-reply@databricks.com>"`

### Task 10: build_reviewer pack

**Cases (payload = build_reviewer keys: position, slide_spec, resolved_style, section_css, resolved_data, html, scripts, deck_brief):**

| case_id | kind | derivation | expect |
|---|---|---|---|
| `clean` | positive | gold slide 1 as `html` | `{criteria: [], positions: []}` — no objective findings |
| `broken_handoff` | mutation | gold slide 1 with the callout's conclusion contradicting the brief's hand-off | `{criteria: [brief_not_delivered], positions: [1]}` |
| `rogue_colour` | mutation | gold slide 1 title recoloured `#E11D48` (off the Meridian palette) | `{criteria: [rogue_colour], positions: [1]}` |
| `overflow` | mutation | gold slide 1 with ~40 bullets appended | `{criteria: [overflow], positions: [1]}` |
| `source_contradiction` | mutation | gold slide 3 figure changed to contradict `resolved_data` | `{criteria: [source_contradiction], positions: [3]}` |

**judge_prompt.md:** used only to confirm the finding's *message* describes the planted fault (the pass/fail is deterministic via `expected_category`). "Given the planted FAULT and the reviewer's FINDINGS, does at least one finding's message describe that fault? PASS/FAIL then one sentence."

Steps mirror Task 9 (generate → judge prompt → self-test asserting the mutation planted the fault, e.g. the rogue hex is present in the mutated html and absent from the gold → commit).

### Task 11: fixer pack

Depends on the Task-cd7d1c3cd product change (fixer unaffected; it's the fix_reviewer that gained `original_html`). **Cases (payload = fixer keys: position, slide_spec, resolved_style, section_css, resolved_data, html, scripts, finding, corrective_instruction):** one per fixable fault — `rogue_colour`, `overflow`, `contrast_failure`, `source_contradiction`, `brief_not_delivered`. Each `html` is the correspondingly-broken gold slide; `finding` is the stamped Finding. Reference = the gold slide before mutation. Judge: "Given the FINDING and the REFERENCE (the known-good original), did the CANDIDATE remove the fault while preserving the slide's message, changing only what the finding required? Use render MEASURES. PASS/FAIL then one sentence." Self-test: the broken input really exhibits the fault (render dirty), the reference renders clean. Steps mirror Task 9.

### Task 12: fix_reviewer pack

**Cases (payload = fix_reviewer keys incl. the new `original_html`, `original_scripts`, `change_summary`):**

| case_id | kind | derivation | expect |
|---|---|---|---|
| `good_fix_accept` | positive | overflow fixed minimally; `original_html` = overflowing, `html` = fixed | `{verdict: fixed, criteria: [], positions: []}` |
| `fault_left_reject` | mutation | `html` still overflows | `{verdict: surfaced, criteria: [overflow], positions: [n]}` |
| `content_broken_reject` | mutation | overflow fixed but a bullet's meaning changed vs `original_html` | `{verdict: surfaced, criteria: [brief_not_delivered], positions: [n]}` |
| `restyle_reject` | mutation | overflow fixed but whole slide recoloured off-palette | `{verdict: surfaced, criteria: [rogue_colour], positions: [n]}` |
| `good_overflow_fix_accept` | positive | contrast fixed minimally | `{verdict: fixed, criteria: [], positions: []}` |

The `content_broken_reject` and `restyle_reject` cases are the ones the product fix (`original_html`) exists to let the reviewer catch. Judge confirms the finding message matches; `expected_category` is the deterministic gate. Steps mirror Task 9.

### Task 13: deck_reviewer pack

**Cases (payload = deck_reviewer keys: narrative_arc, call_to_action, slide_count, slides[{position, html}]):** built from all ten gold slides.

| case_id | kind | derivation | expect |
|---|---|---|---|
| `clean` | positive | all ten slides, correct arc | `{criteria: [], positions: []}` |
| `arc_gap_drop_objections` | mutation | remove slide 8 (objections) | `{criteria: [arc_gap], positions: [-1]}` (deck-level) |
| `repetition` | mutation | duplicate slide 7's point onto slide 5 | `{criteria: [cross_slide_repetition], positions: [-1]}` |
| `missing_conclusion` | mutation | remove slide 9 (verdict/CTA) | `{criteria: [missing_conclusion], positions: [-1]}` |
| `out_of_order` | mutation | swap slides 2 and 7 | `{criteria: [arc_gap], positions: [-1]}` |

Deck-level findings use `slide_index = -1`. Steps mirror Task 9 (no render; the self-test asserts slide counts/content changed as planned).

### Task 14: architect pack

**Cases (payload = architect keys: conversation, message, current_deck_spec, committed_slide_count, previous_deck_review, available_design_contract, template_sections, resolved_style, design_system_library):**

| case_id | kind | message | expect |
|---|---|---|---|
| `build_request` | positive | "Build a deck arguing HTML slides beat PowerPoint" (empty current spec) | `{intent: build}` + judge: spec resembles the gold's shape |
| `edit_request` | mutation | "Make slide 4 use a chart" (current spec = gold) | `{intent: edit, positions: [3]}` |
| `ask_data` | mutation | "Build a deck on OUR Q3 revenue" (no data) | `{intent: ask_data}` |
| `confirm_design` | mutation | "Switch to the Acme design system" | `{intent: confirm_design_contract}` — must NOT set deck_spec |
| `discuss` | positive | "What's the difference between Reveal.js and Slidev?" | `{intent: discuss}` |

**Payload construction:** `message` = the case message; `conversation` = `[{\"role\":\"user\",\"content\": message}]`; `current_deck_spec` = `gold_deck_spec()` for the edit case else `None`; `committed_slide_count` = 10 for edit else 0; `previous_deck_review` = `None`; `available_design_contract` = the Meridian contract `{\"design_system_id\": <meridian>, \"template_id\": <standard>}`; `template_sections` = `[]`; `resolved_style` = `meridian_resolved_style()`; `design_system_library` = `[Meridian, a synthetic second system \"Acme\"]` so `confirm_design` has a switch target.

Judge used only for `build_request` spec quality; others are deterministic on `intent`. Steps mirror Task 9.

### Task 15: data_analyst pack

**Cases (payload = data_analyst keys: data_request, deck_purpose):**

| case_id | kind | data_request | expect |
|---|---|---|---|
| `figures_inline` | positive | request with the three device-render figures stated | `{outcome: success}` + judge: synthesis faithful |
| `two_sources` | positive | request citing two sources to synthesise | `{outcome: success}` |
| `missing_data` | mutation | request for data not supplied and no tool | `{outcome: missing_data}` |
| `needs_tool` | mutation | request that needs Genie (no tool bound) | `{outcome: no_tool}` |
| `conflicting_figures` | mutation | request with two conflicting figures | `{outcome: success}` + judge: flags the conflict, does not invent one value |

Note: the runtime binds no tools, so `needs_tool`/`missing_data` are the realistic outcomes. Steps mirror Task 9.

---

## Task 16: Baseline sweep, calibration, and README

**Files:** Create `evals/README.md`. No code.

- [ ] **Step 1: Calibrate every pack (live, needs a model)**

Run: `python evals/run_eval.py --agent all --calibrate`
Expected: a trust table; every pack `trusted = True`. If any pack is untrusted, fix its `judge_prompt.md` or its reference/mutation before trusting its scores — a judge that cannot tell gold from the planted fault invalidates that pack.

- [ ] **Step 2: Run the v1-baseline sweep (live)**

Run: `python evals/run_eval.py --agent all --config v1-baseline --repeats 3`
Expected: one MLflow run per agent, visible in `mlflow ui --backend-store-uri sqlite:///mlflow.db`, each with overall + per-case pass rate, latency, tokens, cost, and `infra_error` count 0 (or < 10%).

- [ ] **Step 3: Write `evals/README.md`** documenting: the loop (`run_eval.py` flags), how to add a config (`evals/configs/<agent>/<name>.yaml`), how to read the MLflow comparison, calibration, and promotion (`promote.py`), how to regenerate the gold fixtures (`python evals/fixtures/split_gold.py`), and the "judge must be one pinned endpoint across compared configs" rule. Note that `evals/` real-model runs are not collected by CI and that harness self-tests live in `tests/unit/evals/`.

- [ ] **Step 4: Commit**

```bash
git add evals/README.md
git commit -m "docs(evals): baseline sweep notes and harness README

Co-authored-by: Isaac <no-reply@databricks.com>"
```

---

## Done criteria

- `python -m pytest tests/unit/evals -v` is green (CI, no model).
- `python evals/run_eval.py --agent all --calibrate` reports every pack trusted.
- `python evals/run_eval.py --agent all --config v1-baseline --repeats 3` logs seven comparable MLflow runs.
- A second config for any agent can be swept and compared side-by-side in `mlflow ui`.
- `promote.py` with no args rewrites the v1 manifest byte-identically (hashes unchanged) and the pinned-hash suites stay green.
