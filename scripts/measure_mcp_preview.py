"""Dev tool: measure the MCP deck preview of real decks.

Usage: ``uv run python -m scripts.measure_mcp_preview <file>... [--out DIR]``

Each input is an HTML export of a deck or an MCP probe JSON (``body.result.content[0].text``
holding ``{"deck": ...}``). Prints one line per file; ``--out`` writes
``DIR/<input-stem>.preview.html``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.domain.slide_deck import SlideDeck
from src.services.mcp_deck_preview import MCP_RESULT_BUDGET_BYTES, build_deck_preview

DECK_URL = "https://tellr.example/sessions/preview/edit"


def _load_deck(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(json.loads(text)["body"]["result"]["content"][0]["text"])
        return payload["deck"]
    return SlideDeck.from_html_string(text).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
    for path in args.files:
        preview = build_deck_preview(
            _load_deck(path),
            title=None,
            deck_url=DECK_URL,
            svg_assets={},
            max_html_bytes=MCP_RESULT_BUDGET_BYTES,
        )
        size = len(preview.html.encode("utf-8")) if preview.html else 0
        print(
            f"{path.name}: original {path.stat().st_size} B, preview {size} B, "
            f"slides {preview.slides_shown}/{preview.slides_total}, "
            f"images hidden {preview.images_hidden}"
        )
        if args.out is not None and preview.html is not None:
            (args.out / f"{path.stem}.preview.html").write_text(preview.html, encoding="utf-8")


if __name__ == "__main__":
    main()
