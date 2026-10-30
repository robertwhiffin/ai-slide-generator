import json
import pathlib
from dataclasses import dataclass
from typing import Literal
import yaml

EVALS_DIR = pathlib.Path(__file__).resolve().parents[1]   # .../evals
PACKS_DIR = EVALS_DIR / "packs"
MERIDIAN_DIR = EVALS_DIR / "fixtures" / "meridian"
HELDOUT_DIR = MERIDIAN_DIR / "heldout"

SPLITS = ("train", "heldout")
RENDER_REFERENCE_POSITIONS = {"train": (1, 3, 9), "heldout": (0, 1, 2, 3, 5)}


def _check_split(split: str) -> str:
    if split not in SPLITS:
        raise ValueError(f"Invalid split: {split!r} (expected one of {SPLITS})")
    return split


def _deck_dir(deck: str) -> pathlib.Path:
    if deck == "train":
        return MERIDIAN_DIR
    if deck == "heldout":
        return HELDOUT_DIR
    raise ValueError(f"Invalid deck: {deck!r} (expected one of {SPLITS})")


@dataclass(frozen=True)
class Case:
    case_id: str
    agent_key: str
    kind: Literal["positive", "mutation"]
    design_system_active: bool
    fault: str
    payload: dict
    reference: dict
    expect: dict


def cases_dirname(split: str = "train") -> str:
    """Directory name (under a pack) holding the cases for ``split``."""
    _check_split(split)
    return "cases" if split == "train" else "cases_heldout"


def split_kwargs(split: str = "train") -> dict:
    """Keyword args to pass a case loader: empty for train (the default), ``{"split": ...}`` otherwise."""
    return {} if split == "train" else {"split": split}


def cases_dir(agent_key: str, root: pathlib.Path | None = None, split: str = "train") -> pathlib.Path:
    """The directory holding an agent's case dirs: ``root`` if given, else the committed tree for ``split``."""
    _check_split(split)
    if root is not None:
        return pathlib.Path(root)
    return PACKS_DIR / agent_key / cases_dirname(split)


def load_case(agent_key: str, case_id: str, *, root: pathlib.Path | None = None, split: str = "train") -> Case:
    """Load a case from the packs directory (or from ``root``, a generated ``cases`` dir)."""
    case_dir = cases_dir(agent_key, root, split) / case_id

    # Load the three required files
    with open(case_dir / "case.yaml") as f:
        case_data = yaml.safe_load(f)

    with open(case_dir / "payload.json") as f:
        payload = json.load(f)

    with open(case_dir / "reference.json") as f:
        reference = json.load(f)

    # Extract expect from case.yaml or provide empty dict
    expect = case_data.get("expect", {})

    # Validate kind field
    kind = case_data.get("kind")
    if kind not in ("positive", "mutation"):
        raise ValueError(f"Invalid kind: {kind}")

    return Case(
        case_id=case_id,
        agent_key=agent_key,
        kind=kind,
        design_system_active=case_data.get("design_system_active", False),
        fault=case_data.get("fault", ""),
        payload=payload,
        reference=reference,
        expect=expect,
    )


def load_cases(agent_key: str, *, root: pathlib.Path | None = None, split: str = "train") -> list[Case]:
    """Load all cases for an agent, sorted by case_id (from ``root`` if given)."""
    base = cases_dir(agent_key, root, split)

    if not base.exists():
        return []

    case_dirs = sorted([d for d in base.iterdir() if d.is_dir()])
    cases = [load_case(agent_key, d.name, root=root, split=split) for d in case_dirs]

    return sorted(cases, key=lambda c: c.case_id)


def gold_slide(position: int, deck: str = "train") -> str:
    """Load a gold slide HTML by position."""
    with open(_deck_dir(deck) / "gold" / f"{position}.html") as f:
        return f.read()


def gold_scripts(position: int, deck: str = "train") -> str:
    """Load gold slide scripts by position, or empty string if not present."""
    script_path = _deck_dir(deck) / "gold" / f"{position}.js"
    if script_path.exists():
        return script_path.read_text()
    return ""


def meridian_section_css() -> str:
    """Load the Meridian section CSS."""
    with open(MERIDIAN_DIR / "section_css.txt") as f:
        return f.read()


MERIDIAN_TEMPLATE_ENTRY = "templates/standard/index.html"


def meridian_deck_style_context() -> dict:
    """The architect's ``deck_style_context`` for the Meridian bundle, as production derives it.

    Production: the bundle import keeps the declared CSS sources
    (``design_system_service._declared_css_paths``) and the template entry HTML;
    ``materialize_templates`` builds the template row (``token_css`` joined by
    ``_build_token_css``, ``layout_html`` asset-rewritten and root-tag normalised);
    ``resolve_template_bytes`` takes the ``<style>`` CSS out of that layout
    (``_extract_style_blocks_css``, ``""`` when there is none); and ``architect_node``
    sends ``deck_style_context(token_css, style_block, logos)``, with ``logos`` ranked
    by ``rank_logos``.  This runs those same functions over the fixture bundle and
    ``assets.json``, with no database, so it cannot drift from them.
    """
    from types import SimpleNamespace

    from src.domain.deck_style import deck_style_context, rank_logos
    from src.services.design_system_service import _declared_css_paths
    from src.services.design_system_templates import materialize_templates
    from src.services.template_sections import _extract_style_blocks_css

    bundle = MERIDIAN_DIR / "bundle"
    manifest = json.loads((bundle / "_ds_manifest.json").read_text())

    def _file(path: str, kind: str) -> SimpleNamespace:
        return SimpleNamespace(
            path=path, kind=kind, data=(bundle / path).read_bytes(), asset_id=None, mime=""
        )

    files = [_file(p, "css") for p in _declared_css_paths(manifest) if (bundle / p).is_file()]
    files += [_file(t["entryPath"], "template") for t in manifest["templates"]]
    design_system = SimpleNamespace(id=None, manifest_json=manifest, files=files, templates=[])
    template = next(
        t for t in materialize_templates(design_system) if t.entry_path == MERIDIAN_TEMPLATE_ENTRY
    )
    # The fake asset index that stands in for the architect's logo read (production:
    # ``nodes._design_system_logos``), ranked by the same function.
    assets = json.loads((MERIDIAN_DIR / "assets.json").read_text())
    return deck_style_context(
        template.token_css or "",
        _extract_style_blocks_css(template.layout_html or ""),
        rank_logos(assets),
    )


def meridian_resolved_style() -> str:
    """Load the Meridian resolved style."""
    with open(MERIDIAN_DIR / "resolved_style.txt") as f:
        return f.read()


def gold_deck_spec(deck: str = "train") -> dict:
    """Load the gold deck spec JSON."""
    with open(_deck_dir(deck) / "deck_spec.json") as f:
        return json.load(f)
