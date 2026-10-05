import json
import pathlib
from dataclasses import dataclass
from typing import Literal
import yaml


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


def load_case(agent_key: str, case_id: str) -> Case:
    """Load a case from the packs directory."""
    case_dir = pathlib.Path(f"evals/packs/{agent_key}/cases/{case_id}")

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


def load_cases(agent_key: str) -> list[Case]:
    """Load all cases for an agent, sorted by case_id."""
    cases_dir = pathlib.Path(f"evals/packs/{agent_key}/cases")

    if not cases_dir.exists():
        return []

    case_dirs = sorted([d for d in cases_dir.iterdir() if d.is_dir()])
    cases = [load_case(agent_key, d.name) for d in case_dirs]

    return sorted(cases, key=lambda c: c.case_id)


def gold_slide(position: int) -> str:
    """Load a gold slide HTML by position."""
    with open(f"evals/fixtures/meridian/gold/{position}.html") as f:
        return f.read()


def gold_scripts(position: int) -> str:
    """Load gold slide scripts by position, or empty string if not present."""
    script_path = pathlib.Path(f"evals/fixtures/meridian/gold/{position}.js")
    if script_path.exists():
        return script_path.read_text()
    return ""


def meridian_section_css() -> str:
    """Load the Meridian section CSS."""
    with open("evals/fixtures/meridian/section_css.txt") as f:
        return f.read()


def meridian_resolved_style() -> str:
    """Load the Meridian resolved style."""
    with open("evals/fixtures/meridian/resolved_style.txt") as f:
        return f.read()


def gold_deck_spec() -> dict:
    """Load the gold deck spec JSON."""
    with open("evals/fixtures/meridian/deck_spec.json") as f:
        return json.load(f)
