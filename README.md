# HTML Slide Generator

A Python library for generating HTML slide decks using Reveal.js with a clean, modern design.

## Overview

This project provides tools to create professional HTML slide presentations with:
- Clean, modern design using Reveal.js
- Customizable themes and styling
- Support for title slides, agenda slides, and content slides
- LLM-friendly tool functions for programmatic slide creation

## Key Changes: Instance-Based Approach

The library has been refactored to use an **instance-based approach** instead of global state. This means:

1. **Create an HtmlDeck instance**: `deck = HtmlDeck()`
2. **Use tool functions to modify the instance**: `tool_add_title_slide(deck, ...)`
3. **Save or get HTML from the instance**: `tool_save_deck(deck, "output.html")`

## Usage Examples

### Basic Usage

```python
from html_slides import HtmlDeck, tool_add_title_slide, tool_add_agenda_slide

# Create a new deck
deck = HtmlDeck()

# Add slides using tool functions
tool_add_title_slide(
    deck=deck,
    title="My Presentation",
    subtitle="An amazing talk",
    authors=["John Doe"],
    date="2024"
)

tool_add_agenda_slide(
    deck=deck,
    agenda_points=["Introduction", "Main Content", "Conclusion"]
)

# Save the deck
from html_slides import tool_save_deck
tool_save_deck(deck, "output/my_slides.html")
```

### With Custom Theme

```python
from html_slides import HtmlDeck, tool_update_theme

# Create deck with custom theme
deck = HtmlDeck()
theme_json = '{"background_rgb": [245, 245, 245], "accent_rgb": [0, 100, 200]}'
tool_update_theme(deck, theme_json)

# Add slides and save...
```

### LLM Integration

The tool functions are designed to work well with LLMs:

```python
# LLM can call these functions with a deck instance
def llm_create_slides(deck_instance):
    # Add title slide
    tool_add_title_slide(deck_instance, "Title", "Subtitle", ["Author"], "2024")
    
    # Add agenda
    tool_add_agenda_slide(deck_instance, ["Point 1", "Point 2", "Point 3"])
    
    # Add content
    tool_add_content_slide(
        deck_instance,
        "Content Title",
        "Content Subtitle",
        2,
        [["Col 1 Item 1", "Col 1 Item 2"]],
        [["Col 2 Item 1", "Col 2 Item 2"]]
    )
    
    # Save
    tool_save_deck(deck_instance, "output/llm_generated_slides.html")
```

## Available Tool Functions

### Core Functions
- `tool_start_deck(theme_json)` - Create a new deck (returns status message)
- `tool_add_title_slide(deck, title, subtitle, authors, date)` - Add title slide
- `tool_add_agenda_slide(deck, agenda_points)` - Add agenda slide
- `tool_add_content_slide(deck, title, subtitle, num_columns, column_contents)` - Add content slide

### Utility Functions
- `tool_save_deck(deck, output_path)` - Save deck to HTML file
- `tool_get_html(deck)` - Get HTML string from deck
- `tool_get_theme_info(deck)` - Get current theme information
- `tool_update_theme(deck, theme_json)` - Update deck theme

## File Structure

```
python/
├── tools/
│   ├── html_slides.py          # Core library and tool functions
│   └── html_slides_demo.py     # Demo script
├── frontend/
│   └── gradio_frontend.py      # Gradio web interface
└── output/                     # Generated slide files
```

## Running the Demo

```bash
cd python/tools
python html_slides_demo.py
```

## Running the Web Interface

```bash
cd python/frontend
python gradio_frontend.py
```

## Benefits of the New Approach

1. **No Global State**: Each deck is independent
2. **Better Testability**: Easy to create multiple decks in tests
3. **Cleaner API**: Functions explicitly take the deck they operate on
4. **More Flexible**: Can work with multiple decks simultaneously
5. **LLM Friendly**: Clear parameter passing makes it easier for LLMs to use

## Migration from Old Global Approach

If you were using the old global approach:

**Old (Global State)**:
```python
tool_start_deck()
tool_add_title_slide("Title", "Subtitle", ["Author"], "2024")
html = tool_get_html()
```

**New (Instance-Based)**:
```python
deck = HtmlDeck()
tool_add_title_slide(deck, "Title", "Subtitle", ["Author"], "2024")
html = tool_get_html(deck)
```

## Theme Customization

Themes can be customized via JSON:

```json
{
  "background_rgb": [245, 245, 245],
  "font_family": "Arial, sans-serif",
  "title_color_rgb": [0, 0, 0],
  "accent_rgb": [0, 100, 200],
  "logo_url": "https://example.com/logo.png",
  "footer_text": "Company Name"
}
```

## Dependencies

- Python 3.7+
- No external dependencies for core functionality
- Gradio for web interface (optional)
