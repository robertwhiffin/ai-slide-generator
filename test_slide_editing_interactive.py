"""
Interactive test script for slide editing functionality.

This script demonstrates the complete editing flow:
1. Generate initial slide deck
2. Display slides with indices
3. Prompt user to select slides for editing
4. Send edit request with slide context
5. Display results and verify replacements
6. Save all outputs for inspection
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.agent import create_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output/slide_editing_test")
DEBUG_DIR = OUTPUT_DIR / "debug"
BASE_PROMPT = (
    "YOU ARE IN DEV MODE. DO NOT USE TOOLS. Create 6 slides that cover: "
    "title page, business context, current metrics, risks, opportunities, "
    "and a conclusion with consistent styling."
)


def print_header(title: str) -> None:
    """Print formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_slide_summary(deck: SlideDeck) -> None:
    """Print summary of slides in deck."""
    print(f"Deck contains {len(deck)} slides:\n")
    for idx, slide in enumerate(deck.slides):
        html = slide.to_html()
        if "<h1>" in html:
            title = html.split("<h1>")[1].split("</h1>")[0][:50]
        elif "<h2>" in html:
            title = html.split("<h2>")[1].split("</h2>")[0][:50]
        else:
            title = "Untitled slide"
        print(f"  [{idx}] {title}")


def _save_deck(deck: SlideDeck, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(path)
    logger.info("Saved deck", extra={"path": str(path)})


def _save_raw_html(content: str, filename: str) -> None:
    """Write raw LLM HTML for debugging."""
    if not content:
        return
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_path = DEBUG_DIR / filename
    debug_path.write_text(content, encoding="utf-8")
    logger.info("Saved raw HTML", extra={"path": str(debug_path)})


def _apply_replacements(deck: SlideDeck, replacement_info: dict) -> None:
    start = replacement_info["start_index"]
    original_count = replacement_info["original_count"]

    for _ in range(original_count):
        deck.remove_slide(start)

    for idx, slide_html in enumerate(replacement_info["replacement_slides"]):
        new_slide = Slide(html=slide_html, slide_id=f"slide_{start + idx}")
        deck.insert_slide(new_slide, start + idx)

    replacement_scripts = replacement_info.get("replacement_scripts", "")
    if replacement_scripts and replacement_scripts.strip():
        cleaned = replacement_scripts.strip()
        if deck.scripts:
            deck.scripts = f"{deck.scripts.rstrip()}\n\n{cleaned}\n"
        else:
            deck.scripts = f"{cleaned}\n"


def _run_edit(
    agent,
    session_id: str,
    deck: SlideDeck,
    indices: Iterable[int],
    instruction: str,
    max_slides: int = 10,
) -> dict:
    selected_indices = list(indices)
    selected_htmls = [deck.slides[i].to_html() for i in selected_indices]
    slide_context = {"indices": selected_indices, "slide_htmls": selected_htmls}

    result = agent.generate_slides(
        question=instruction,
        session_id=session_id,
        max_slides=max_slides,
        slide_context=slide_context,
    )

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    indices_slug = "-".join(str(idx) for idx in selected_indices)
    _save_raw_html(result.get("html", ""), f"edit_raw_{indices_slug}_{timestamp}.html")

    replacement_info = result["replacement_info"]

    print("Replacement Results:")
    print(f"  Start index: {replacement_info['start_index']}")
    print(f"  Original count: {replacement_info['original_count']}")
    print(f"  Replacement count: {replacement_info['replacement_count']}")
    print(f"  Net change: {replacement_info['replacement_count'] - replacement_info['original_count']}")
    print(f"  Success: {replacement_info['success']}")

    _apply_replacements(deck, replacement_info)
    return replacement_info


def _prepare_base_deck(agent) -> str:
    """Generate the shared base deck once and return its HTML."""
    print_header("Generating Shared Base Deck")
    session_id = agent.create_session()
    result = agent.generate_slides(
        question=BASE_PROMPT,
        session_id=session_id,
        max_slides=6,
    )

    base_html = result["html"]
    _save_raw_html(base_html, "base_deck_raw.html")
    base_deck = SlideDeck.from_html_string(base_html)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _save_deck(base_deck, OUTPUT_DIR / "base_deck.html")
    print(f"✓ Base deck generated with {len(base_deck)} slides")
    print_slide_summary(base_deck)

    # Clean up generation session to keep memory tidy
    agent.clear_session(session_id)

    return base_html


def _clone_base_deck(base_html: str) -> SlideDeck:
    """Return a fresh SlideDeck parsed from the shared base HTML."""
    return SlideDeck.from_html_string(base_html)


def test_1to1_replacement(agent, base_html: str) -> None:
    """Test 1:1 slide replacement (same number in and out)."""
    print_header("TEST 1: 1:1 Replacement (2 slides → 2 slides)")

    session_id = agent.create_session()
    deck = _clone_base_deck(base_html)
    print(f"Using shared base deck with {len(deck)} slides")
    print_slide_summary(deck)

    _save_deck(deck, OUTPUT_DIR / "test1_initial.html")

    print("\nSelecting slides [2, 3] for editing...")
    print("Edit request: Change to blue color scheme\n")

    replacement_info = _run_edit(
        agent,
        session_id,
        deck,
        indices=[2, 3],
        instruction="Change these slides to use a blue color scheme (#1E40AF for headers)",
        max_slides=5,
    )

    print("\n✓ Applied replacements")
    print_slide_summary(deck)

    _save_deck(deck, OUTPUT_DIR / "test1_edited_1to1.html")
    print(f"\n✓ Saved to {OUTPUT_DIR / 'test1_edited_1to1.html'}")


def test_expansion(agent, base_html: str) -> None:
    """Test expansion (2 slides → 4 slides)."""
    print_header("TEST 2: Expansion (2 slides → 4 slides)")

    session_id = agent.create_session()
    deck = _clone_base_deck(base_html)
    print(f"Using shared base deck with {len(deck)} slides")
    print_slide_summary(deck)

    _save_deck(deck, OUTPUT_DIR / "test2_initial.html")

    print("\nSelecting slides [1, 2] for expansion...")
    print("Edit request: Expand into more detailed slides\n")

    replacement_info = _run_edit(
        agent,
        session_id,
        deck,
        indices=[1, 2],
        instruction="Expand these 2 slides into 4 more detailed slides with quarterly breakdowns. DO NOT USE TOLS. Create a small synthetic dataset",
        max_slides=10,
    )

    print(f"\n✓ Deck now has {len(deck)} slides (was 4)")
    print_slide_summary(deck)

    _save_deck(deck, OUTPUT_DIR / "test2_edited_expansion.html")
    print(f"\n✓ Saved to {OUTPUT_DIR / 'test2_edited_expansion.html'}")


def test_condensation(agent, base_html: str) -> None:
    """Test condensation (3 slides → 1 slide)."""
    print_header("TEST 3: Condensation (3 slides → 1 slide)")

    session_id = agent.create_session()
    deck = _clone_base_deck(base_html)
    print(f"Using shared base deck with {len(deck)} slides")
    print_slide_summary(deck)

    _save_deck(deck, OUTPUT_DIR / "test3_initial.html")

    print("\nSelecting slides [2, 3, 4] for condensation...")
    print("Edit request: Condense into a single summary slide\n")

    replacement_info = _run_edit(
        agent,
        session_id,
        deck,
        indices=[2, 3, 4],
        instruction="Condense these 3 feature slides into 1 comprehensive summary slide",
        max_slides=6,
    )

    print(f"\n✓ Deck now has {len(deck)} slides (was 6)")
    print_slide_summary(deck)

    _save_deck(deck, OUTPUT_DIR / "test3_edited_condensation.html")
    print(f"\n✓ Saved to {OUTPUT_DIR / 'test3_edited_condensation.html'}")


def test_interactive_mode(agent, base_html: str) -> None:
    """Interactive mode where user can repeatedly edit slides."""
    print_header("TEST 4: Interactive Mode")

    session_id = agent.create_session()
    deck = _clone_base_deck(base_html)
    print(f"Using shared base deck with {len(deck)} slides")

    interactive_dir = OUTPUT_DIR / "interactive"
    interactive_dir.mkdir(parents=True, exist_ok=True)

    iteration = 0
    _save_deck(deck, interactive_dir / f"deck_v{iteration}.html")

    while True:
        print("\n" + "-" * 80)
        print_slide_summary(deck)
        print("-" * 80)

        print("\nOptions:")
        print("  1. Edit slides (enter indices like '2,3' or '0-2')")
        print("  2. Save and exit")

        choice = input("\nChoice: ").strip()

        if choice == "2":
            print("\n✓ Exiting interactive mode")
            break

        if choice != "1":
            print("❌ Invalid choice")
            continue

        indices_input = input("Enter slide indices (e.g., '2,3' or '1-3'): ").strip()
        if "-" in indices_input:
            start, end = map(int, indices_input.split("-"))
            selected_indices = list(range(start, end + 1))
        else:
            selected_indices = [int(value.strip()) for value in indices_input.split(",")]

        if any(idx < 0 or idx >= len(deck) for idx in selected_indices):
            print("❌ Invalid indices")
            continue

        edit_instruction = input("What changes do you want to make? ").strip()
        if not edit_instruction:
            print("❌ No instruction provided")
            continue

        print("\nProcessing edit...")
        replacement_info = _run_edit(
            agent,
            session_id,
            deck,
            indices=selected_indices,
            instruction=edit_instruction,
            max_slides=10,
        )

        print(f"✓ Replaced {replacement_info['original_count']} slides with {replacement_info['replacement_count']} slides")

        iteration += 1
        _save_deck(deck, interactive_dir / f"deck_v{iteration}.html")
        print(f"✓ Saved version {iteration}")


def main() -> None:
    """Entry point for interactive test script."""
    print_header("Slide Editing Backend Tests")

    agent = create_agent()
    base_html = _prepare_base_deck(agent)

    print("Available tests:")
    print("  1. Test 1:1 Replacement (2 slides → 2 slides)")
    print("  2. Test Expansion (2 slides → 4 slides)")
    print("  3. Test Condensation (3 slides → 1 slide)")
    print("  4. Interactive Mode (manual testing)")
    print("  5. Run all automated tests")

    choice = input("\nSelect test (1-5): ").strip()

    try:
        if choice == "1":
            test_1to1_replacement(agent, base_html)
        elif choice == "2":
            test_expansion(agent, base_html)
        elif choice == "3":
            test_condensation(agent, base_html)
        elif choice == "4":
            test_interactive_mode(agent, base_html)
        elif choice == "5":
            test_1to1_replacement(agent, base_html)
            test_expansion(agent, base_html)
            test_condensation(agent, base_html)
            print_header("All Tests Complete")
            print(f"Check {OUTPUT_DIR} for results")
        else:
            print("Invalid choice")
    except Exception as exc:
        print(f"\n❌ Test failed: {exc}")
        logger.exception("Test error")


if __name__ == "__main__":
    main()

