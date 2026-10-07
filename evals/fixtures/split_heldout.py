"""Split deck 2 ("Prompt Optimisation: A Practical Framework") into held-out gold fixtures.

Reads ~/Downloads/prompt-optimisation--a-practical-framework.html and ~/Downloads/test deck spec 2.
Writes evals/fixtures/meridian/heldout/gold/<0..5>.html and heldout/deck_spec.json. Idempotent.
"""
import json
import pathlib
import re

HTML_SRC = pathlib.Path.home() / "Downloads/prompt-optimisation--a-practical-framework.html"
SPEC_SRC = pathlib.Path.home() / "Downloads/test deck spec 2"
OUT = pathlib.Path("evals/fixtures/meridian/heldout")
TITLE = "Prompt Optimisation: A Practical Framework"
SOURCE = "Held-out deck fixture"

SYNTHESIS = (
    "Structured prompting beats ad-hoc prompting on token cost, output consistency and the number "
    "of revision rounds needed to reach production quality."
)
FIGURES = [
    ("token_cost_reduction", "30–50% fewer tokens per request vs. naive prompts"),
    ("consistency_gain", "up to 40% output consistency gain with few-shot + chain-of-thought"),
    ("iteration_cycles", "3–5 revision rounds to reach production-grade quality"),
]
STAT_POSITION = 3

FIELDS = {
    "audience": "Audience",
    "purpose": "Purpose",
    "argument": "Argument",
    "call_to_action": "Call to action",
}


def split_slides(html: str) -> list[str]:
    sections = re.findall(r'<div class="slide-container">\s*(<section.*?</section>)', html, re.S)
    assert len(sections) == 6, f"expected 6 slides, got {len(sections)}"
    for pos, sec in enumerate(sections):
        assert "<style" not in sec.lower(), f"slide {pos} leaked a <style> block"
        assert "slide-wrapper" not in sec and "slide-container" not in sec
    return sections


def parse_spec(text: str) -> dict:
    lines = [ln.rstrip() for ln in text.splitlines()]
    headers = ["Audience", "Purpose", "Argument", "Call to action", "Narrative arc", "Design contract", "Slide briefs"]
    idx = {h: lines.index(h) for h in headers}
    order = sorted(idx.items(), key=lambda kv: kv[1])

    def body(h: str) -> list[str]:
        start = idx[h] + 1
        end = next((i for n, i in order if i > idx[h]), len(lines))
        return [ln.strip() for ln in lines[start:end] if ln.strip()]

    spec: dict = {"title": TITLE}
    for key, h in FIELDS.items():
        spec[key] = " ".join(body(h))
    spec["narrative_arc"] = body("Narrative arc")
    m = re.search(r"Design system #(\d+)\s*Template #(\d+)", " ".join(body("Design contract")))
    assert m, "design contract line not found"
    spec["design_contract"] = {"design_system_id": int(m.group(1)), "template_id": int(m.group(2))}
    spec["resolved_data"] = {
        "synthesis": SYNTHESIS,
        "figures": [{"key": k, "value": v, "source": SOURCE} for k, v in FIGURES],
        "gaps": [],
    }

    blocks = re.split(r"^Slide (\d+)\s*$", "\n".join(lines[idx["Slide briefs"] + 1:]), flags=re.M)
    slides = []
    for num, blk in zip(blocks[1::2], blocks[2::2]):
        paras = [p.strip() for p in re.split(r"\n\s*\n", blk.strip())]
        assert len(paras) == 4, f"slide {num}: expected 4 paragraphs, got {len(paras)}"
        purpose_, brief, assumes, hands = paras
        assert assumes.startswith("Assumes:") and hands.startswith("Hands off:")
        pos = int(num) - 1
        slides.append({
            "position": pos,
            "purpose": purpose_,
            "content_brief": brief,
            "assumes": assumes[len("Assumes:"):].strip(),
            "hands_off": hands[len("Hands off:"):].strip(),
            "data_references": [k for k, _ in FIGURES] if pos == STAT_POSITION else [],
        })
    assert [s["position"] for s in slides] == list(range(6))
    spec["slides"] = slides
    return spec


def main() -> None:
    sections = split_slides(HTML_SRC.read_text())
    (OUT / "gold").mkdir(parents=True, exist_ok=True)
    for pos, sec in enumerate(sections):
        (OUT / "gold" / f"{pos}.html").write_text(sec.strip() + "\n")
    spec = parse_spec(SPEC_SRC.read_text())
    (OUT / "deck_spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    print("wrote", len(sections), "slides and deck_spec.json")


if __name__ == "__main__":
    main()
