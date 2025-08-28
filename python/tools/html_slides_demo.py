from __future__ import annotations

from pathlib import Path

# Adjust import for direct script execution
import sys
from pathlib import Path as _Path
sys.path.append(str(_Path(__file__).resolve().parents[2]))

from python.tools.html_slides import HtmlDeck, SlideTheme


def run_demo() -> Path:
    out_dir = Path("./output").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    theme = SlideTheme(
        background_rgb=(245, 246, 250),
        font_family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        title_font_size_px=44,
        subtitle_font_size_px=24,
        body_font_size_px=18,
        title_color_rgb=(20, 20, 20),
        subtitle_color_rgb=(80, 80, 80),
        body_color_rgb=(30, 30, 30),
    )

    deck = HtmlDeck(theme=theme)
    deck.add_title_slide(
        title="Project Title",
        subtitle="Subtitle goes here",
        authors=["Alice", "Bob"],
        date="2025-08-26",
    )
    deck.add_agenda_slide(agenda_points=["Introduction", "Approach", "Results", "Next Steps"])
    deck.add_agenda_slide(agenda_points=[
        "Item 1","Item 2","Item 3","Item 4","Item 5","Item 6","Item 7"
    ])
    deck.add_agenda_slide(agenda_points=[
        "P1","P2","P3","P4","P5","P6","P7","P8","P9","P10","P11","P12"
    ])
    deck.add_content_slide(
        title="Content Slide",
        subtitle="Two columns example",
        num_columns=2,
        column_contents=[["Point A1", "Point A2"], ["Point B1", "Point B2"]],
    )
    deck.add_content_slide(
        title="Content 1-Column",
        subtitle="Single column layout",
        num_columns=1,
        column_contents=[["Single A1", "Single A2", "Single A3"]],
    )
    deck.add_content_slide(
        title="Content 3-Columns",
        subtitle="Three column layout",
        num_columns=3,
        column_contents=[
            ["Col1 A", "Col1 B", "Col1 C"],
            ["Col2 A", "Col2 B", "Col2 C"],
            ["Col3 A", "Col3 B", "Col3 C"],
        ],
    )

    html = deck.to_html()
    out_path = out_dir / "demo_slides.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    out = run_demo()
    print(f"Wrote HTML to: {out}")
