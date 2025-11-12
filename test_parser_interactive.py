#!/usr/bin/env python
"""
Interactive test script for the SlideDeck HTML parser.

This script helps debug HTML parsing issues by:
- Loading HTML from files or generating via agent
- Parsing with SlideDeck.from_html_string()
- Displaying detailed parsing results
- Saving parsed/reconstructed HTML for comparison
- Interactive prompts for debugging

Usage:
    # Parse existing HTML file
    python test_parser_interactive.py output/slides_20241112_120000.html
    
    # Generate fresh HTML and parse
    python test_parser_interactive.py --generate
    
    # Generate with custom question
    python test_parser_interactive.py --generate --question "Your question"
    
    # Verbose output for debugging
    python test_parser_interactive.py output/slides.html --verbose
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from src.models.slide_deck import SlideDeck
from src.models.slide import Slide


def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def print_section(text: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'─' * 80}")
    print(f"  {text}")
    print('─' * 80)


def print_result(key: str, value: Any) -> None:
    """Print a key-value result."""
    if isinstance(value, str) and len(value) > 100:
        print(f"  {key}: {value[:100]}... ({len(value)} chars)")
    else:
        print(f"  {key}: {value}")


def generate_slides(question: str, max_slides: int = 5) -> str:
    """Generate slides using the agent."""
    print_section("🤖 Generating Slides with Agent")
    
    # Check credentials
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    
    if not host or not token:
        print("❌ ERROR: Databricks credentials not set!")
        print("\nSet environment variables:")
        print("  export DATABRICKS_HOST='https://your-workspace.cloud.databricks.com'")
        print("  export DATABRICKS_TOKEN='your-token'")
        sys.exit(1)
    
    from src.services.agent import create_agent
    
    print(f"Question: {question}")
    print(f"Max slides: {max_slides}")
    print("\nCalling agent...")
    
    agent = create_agent()
    result = agent.generate_slides(question=question, max_slides=max_slides)
    
    html = result.get("html", "")
    print(f"✅ Generated {len(html):,} characters of HTML")
    print(f"   Tool calls: {result['metadata']['tool_calls']}")
    print(f"   Time: {result['metadata']['latency_seconds']:.1f}s")
    
    return html


def load_html(file_path: Path) -> str:
    """Load HTML from file."""
    if not file_path.exists():
        print(f"❌ ERROR: File not found: {file_path}")
        sys.exit(1)
    
    html = file_path.read_text(encoding='utf-8')
    print(f"✅ Loaded {len(html):,} characters from {file_path}")
    return html


def parse_html(html: str, verbose: bool = False) -> SlideDeck:
    """Parse HTML into SlideDeck."""
    print_section("🔍 Parsing HTML with SlideDeck")
    
    try:
        deck = SlideDeck.from_html_string(html)
        
        print("✅ Parsing successful!")
        print_result("Title", deck.title or "(no title)")
        print_result("Slide count", len(deck.slides))
        print_result("CSS length", f"{len(deck.css):,} chars")
        print_result("Scripts length", f"{len(deck.scripts):,} chars")
        print_result("External scripts", len(deck.external_scripts))
        
        if deck.external_scripts:
            for src in deck.external_scripts:
                print(f"    - {src}")
        
        # Show slide details
        print("\n  Slides:")
        for idx, slide in enumerate(deck.slides):
            print(f"    [{idx}] {slide.slide_id} - {len(slide.html):,} chars")
            
            if verbose:
                # Extract slide title if present
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(slide.html, 'html.parser')
                h1 = soup.find('h1')
                h2 = soup.find('h2')
                title = h1.get_text() if h1 else (h2.get_text() if h2 else "(no title)")
                print(f"         Title: {title[:50]}")
        
        return deck
        
    except Exception as e:
        print(f"\n❌ PARSING FAILED!")
        print(f"   Error: {e}")
        
        if verbose:
            import traceback
            print("\nFull traceback:")
            traceback.print_exc()
        
        sys.exit(1)


def analyze_parsing(html: str, deck: SlideDeck, verbose: bool = False) -> None:
    """Analyze parsing quality."""
    print_section("📊 Parsing Analysis")
    
    # Count slides in original HTML
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    original_slides = soup.find_all('div', class_='slide')
    
    print(f"  Original HTML: {len(original_slides)} slides found")
    print(f"  Parsed deck: {len(deck.slides)} slides")
    
    if len(original_slides) != len(deck.slides):
        print("  ⚠️  WARNING: Slide count mismatch!")
    else:
        print("  ✅ Slide count matches")
    
    # Check CSS preservation
    original_styles = soup.find_all('style')
    total_css = sum(len(s.string or '') for s in original_styles)
    
    print(f"\n  Original CSS: {total_css:,} chars")
    print(f"  Parsed CSS: {len(deck.css):,} chars")
    
    if abs(total_css - len(deck.css)) > 10:
        print("  ⚠️  WARNING: CSS length differs significantly")
    else:
        print("  ✅ CSS preserved")
    
    # Check scripts
    original_scripts = soup.find_all('script', src=False)
    total_scripts = sum(len(s.string or '') for s in original_scripts)
    
    print(f"\n  Original scripts: {total_scripts:,} chars")
    print(f"  Parsed scripts: {len(deck.scripts):,} chars")
    
    if abs(total_scripts - len(deck.scripts)) > 10:
        print("  ⚠️  WARNING: Script length differs significantly")
    else:
        print("  ✅ Scripts preserved")
    
    # Check external scripts
    original_ext = soup.find_all('script', src=True)
    
    print(f"\n  Original external scripts: {len(original_ext)}")
    print(f"  Parsed external scripts: {len(deck.external_scripts)}")
    
    if len(original_ext) != len(deck.external_scripts):
        print("  ⚠️  WARNING: External script count differs")
    else:
        print("  ✅ External scripts preserved")


def save_outputs(
    original_html: str,
    deck: SlideDeck,
    output_dir: Path = Path("output/parser_test")
) -> Dict[str, Path]:
    """Save original and reconstructed HTML for comparison."""
    print_section("💾 Saving Outputs")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    files = {}
    
    # Save original HTML
    original_file = output_dir / f"original_{timestamp}.html"
    original_file.write_text(original_html, encoding='utf-8')
    files['original'] = original_file
    print(f"  Original: {original_file}")
    
    # Save reconstructed HTML (knitted)
    reconstructed_html = deck.knit()
    reconstructed_file = output_dir / f"reconstructed_{timestamp}.html"
    reconstructed_file.write_text(reconstructed_html, encoding='utf-8')
    files['reconstructed'] = reconstructed_file
    print(f"  Reconstructed: {reconstructed_file}")
    
    # Save individual slides
    slides_dir = output_dir / f"slides_{timestamp}"
    slides_dir.mkdir(exist_ok=True)
    
    for idx, slide in enumerate(deck.slides):
        slide_html = deck.render_slide(idx)
        slide_file = slides_dir / f"slide_{idx:02d}.html"
        slide_file.write_text(slide_html, encoding='utf-8')
    
    files['slides_dir'] = slides_dir
    print(f"  Individual slides: {slides_dir}/ ({len(deck.slides)} files)")
    
    # Save JSON representation
    import json
    json_file = output_dir / f"deck_{timestamp}.json"
    json_file.write_text(json.dumps(deck.to_dict(), indent=2), encoding='utf-8')
    files['json'] = json_file
    print(f"  JSON: {json_file}")
    
    return files


def interactive_menu(html: str, deck: SlideDeck) -> None:
    """Interactive debugging menu."""
    print_section("🔧 Interactive Debugging")
    
    while True:
        print("\nOptions:")
        print("  1) Show deck summary")
        print("  2) Show slide details")
        print("  3) Show CSS")
        print("  4) Show scripts")
        print("  5) Show external scripts")
        print("  6) Compare original vs reconstructed HTML lengths")
        print("  7) Inspect specific slide")
        print("  8) Save outputs")
        print("  q) Quit")
        
        choice = input("\nChoice: ").strip().lower()
        
        if choice == 'q':
            break
        elif choice == '1':
            print(f"\nTitle: {deck.title}")
            print(f"Slides: {len(deck.slides)}")
            print(f"CSS: {len(deck.css):,} chars")
            print(f"Scripts: {len(deck.scripts):,} chars")
            print(f"External: {len(deck.external_scripts)} scripts")
        
        elif choice == '2':
            for idx, slide in enumerate(deck.slides):
                print(f"\n[{idx}] {slide.slide_id}")
                print(f"    HTML: {len(slide.html):,} chars")
                # Extract title
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(slide.html, 'html.parser')
                h1 = soup.find('h1')
                h2 = soup.find('h2')
                title = h1.get_text() if h1 else (h2.get_text() if h2 else "(no title)")
                print(f"    Title: {title}")
        
        elif choice == '3':
            print(f"\nCSS ({len(deck.css):,} chars):")
            print(deck.css[:500])
            if len(deck.css) > 500:
                print(f"... ({len(deck.css) - 500} more chars)")
        
        elif choice == '4':
            print(f"\nScripts ({len(deck.scripts):,} chars):")
            print(deck.scripts[:500])
            if len(deck.scripts) > 500:
                print(f"... ({len(deck.scripts) - 500} more chars)")
        
        elif choice == '5':
            print("\nExternal scripts:")
            for src in deck.external_scripts:
                print(f"  - {src}")
        
        elif choice == '6':
            reconstructed = deck.knit()
            print(f"\nOriginal: {len(html):,} chars")
            print(f"Reconstructed: {len(reconstructed):,} chars")
            print(f"Difference: {len(reconstructed) - len(html):+,} chars")
        
        elif choice == '7':
            idx_str = input("Slide index: ").strip()
            try:
                idx = int(idx_str)
                if 0 <= idx < len(deck.slides):
                    slide = deck.slides[idx]
                    print(f"\nSlide {idx} ({slide.slide_id}):")
                    print(slide.html)
                else:
                    print(f"Invalid index. Must be 0-{len(deck.slides)-1}")
            except ValueError:
                print("Invalid input. Enter a number.")
        
        elif choice == '8':
            save_outputs(html, deck)
            print("✅ Outputs saved!")
        
        else:
            print("Invalid choice")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive SlideDeck parser tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'file',
        nargs='?',
        help='HTML file to parse (if not using --generate)'
    )
    
    parser.add_argument(
        '--generate',
        action='store_true',
        help='Generate fresh HTML using agent'
    )
    
    parser.add_argument(
        '--question',
        default="I want a 5 slide consumption review of KPMG UK, starting from November 2024.",
        help='Question for agent (with --generate)'
    )
    
    parser.add_argument(
        '--max-slides',
        type=int,
        default=5,
        help='Max slides to generate (with --generate)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Verbose output for debugging'
    )
    
    parser.add_argument(
        '--save',
        action='store_true',
        help='Save outputs immediately (skip interactive menu)'
    )
    
    parser.add_argument(
        '--no-interactive',
        action='store_true',
        help='Skip interactive menu'
    )
    
    args = parser.parse_args()
    
    # Determine HTML source
    if args.generate:
        html = generate_slides(args.question, args.max_slides)
        
        # Optionally save generated HTML
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        gen_file = output_dir / f"generated_{timestamp}.html"
        gen_file.write_text(html, encoding='utf-8')
        print(f"\n💾 Saved generated HTML: {gen_file}")
    
    elif args.file:
        file_path = Path(args.file)
        html = load_html(file_path)
    
    else:
        print("❌ ERROR: Must provide file or use --generate")
        parser.print_help()
        sys.exit(1)
    
    print_header("SlideDeck Parser Interactive Test")
    
    # Parse HTML
    deck = parse_html(html, verbose=args.verbose)
    
    # Analyze
    analyze_parsing(html, deck, verbose=args.verbose)
    
    # Save outputs if requested
    if args.save:
        save_outputs(html, deck)
    
    # Interactive menu unless disabled
    if not args.no_interactive:
        try:
            interactive_menu(html, deck)
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
    
    print("\n✅ Test complete!")


if __name__ == "__main__":
    main()

