"""Demo script showing slide parser capabilities."""

import sys
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import SlideDeck, Slide


def main():
    """Demonstrate slide parser functionality."""
    
    # Find an existing slide deck in output/
    output_dir = Path("output")
    html_files = list(output_dir.glob("*.html"))
    
    if not html_files:
        print("No HTML files found in output/ directory")
        print("Generate some slides first using the agent")
        return
    
    # Use the first HTML file found
    input_file = html_files[0]
    print(f"\n📄 Parsing slide deck: {input_file.name}")
    print("=" * 60)
    
    # Parse the HTML file
    deck = SlideDeck.from_html(str(input_file))
    
    # Display basic info
    print(f"\n✅ Successfully parsed slide deck!")
    print(f"   Title: {deck.title}")
    print(f"   Number of slides: {len(deck)}")
    print(f"   CSS length: {len(deck.css)} characters")
    print(f"   JavaScript length: {len(deck.scripts)} characters")
    print(f"   External scripts: {len(deck.external_scripts)}")
    
    if deck.external_scripts:
        for script in deck.external_scripts:
            print(f"      - {script}")
    
    # Show preview of each slide
    print(f"\n📑 Slide Preview:")
    print("-" * 60)
    for i, slide in enumerate(deck):
        preview = slide.html[:80].replace('\n', ' ')
        print(f"   Slide {i + 1}: {preview}...")
    
    # Demonstrate manipulation
    print(f"\n🔧 Demonstrating slide manipulation:")
    print("-" * 60)
    
    # Clone first slide
    if len(deck) > 0:
        cloned = deck[0].clone()
        print(f"   ✓ Cloned slide 1")
        
        # Insert cloned slide at position 1
        deck.insert_slide(cloned, position=1)
        print(f"   ✓ Inserted clone at position 2")
        print(f"   ✓ New slide count: {len(deck)}")
    
    # Swap two slides if we have enough
    if len(deck) >= 3:
        print(f"   ✓ Swapping slides 2 and 3")
        deck.swap_slides(1, 2)
    
    # Save modified deck
    output_file = output_dir / "demo_modified_slides.html"
    deck.save(str(output_file))
    print(f"\n💾 Saved modified deck to: {output_file.name}")
    
    # Show JSON representation
    print(f"\n📊 JSON representation (for APIs):")
    print("-" * 60)
    deck_dict = deck.to_dict()
    print(f"   slide_count: {deck_dict['slide_count']}")
    print(f"   title: {deck_dict['title']}")
    print(f"   Number of slide objects: {len(deck_dict['slides'])}")
    
    # Demonstrate rendering individual slide
    if len(deck) > 0:
        print(f"\n🎬 Rendering individual slide (for web viewers):")
        print("-" * 60)
        single_slide_html = deck.render_slide(0)
        print(f"   ✓ Rendered slide 1 as standalone HTML")
        print(f"   ✓ HTML length: {len(single_slide_html)} characters")
        
        # Save individual slide
        single_output = output_dir / "demo_single_slide.html"
        Path(single_output).write_text(single_slide_html)
        print(f"   ✓ Saved to: {single_output.name}")
    
    print(f"\n✨ Demo complete!")
    print(f"   Check output/ directory for generated files")


if __name__ == "__main__":
    main()

