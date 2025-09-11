#!/usr/bin/env python3
"""Test script for visual-aware PPTX conversion."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from slide_generator.tools.html_to_pptx import HtmlToPptxConverter
from slide_generator.tools.html_slides import HtmlDeck


async def test_visual_pptx_conversion():
    """Test visual PPTX conversion with the test HTML file."""
    print("Starting visual PPTX conversion test...")
    
    # Path to test HTML file
    test_html_path = Path("test/output/test_1_output.html")
    if not test_html_path.exists():
        print(f"Error: Test HTML file not found at {test_html_path}")
        return False
    
    try:
        # Create a dummy HtmlDeck with minimal structure for testing
        # We'll load the HTML content directly since we're testing existing HTML
        html_deck = HtmlDeck()
        
        # Read the HTML content
        with open(test_html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Override the to_html method to return our test content
        html_deck._test_html_content = html_content
        original_to_html = html_deck.to_html
        html_deck.to_html = lambda: html_deck._test_html_content
        
        # Parse slides from HTML content (basic extraction)
        # Count sections to determine number of slides
        import re
        sections = re.findall(r'<section[^>]*>(.*?)</section>', html_content, re.DOTALL)
        print(f"Found {len(sections)} slides in HTML content")
        
        # Create dummy slide objects for the converter
        from slide_generator.tools.html_slides import Slide
        html_deck._slides = []
        for i, section_content in enumerate(sections):
            slide = Slide(
                slide_type="content",
                title=f"Slide {i+1}",
                subtitle="",
                content=section_content,
                metadata={}
            )
            html_deck._slides.append(slide)
        
        # Initialize converter
        converter = HtmlToPptxConverter(html_deck)
        
        # Convert to PPTX
        output_path = "test/output/test_visual_conversion.pptx"
        print(f"Converting HTML to PPTX: {output_path}")
        
        result_path = await converter.convert_to_pptx(output_path, include_charts=True)
        
        print(f"✅ Success! PPTX created at: {result_path}")
        
        # Check file size
        output_file = Path(result_path)
        if output_file.exists():
            file_size = output_file.stat().st_size
            print(f"📊 File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
            
            if file_size > 50000:  # More than 50KB suggests visual content was captured
                print("🎯 File size indicates visual content was likely captured successfully!")
            else:
                print("⚠️  Small file size might indicate visual capture issues")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during conversion: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run the test
    success = asyncio.run(test_visual_pptx_conversion())
    
    if success:
        print("\n🎉 Test completed successfully!")
        print("Next steps:")
        print("1. Open the generated PPTX file to check visual quality")
        print("2. Verify that the EY Parthenon logo appears in bottom-right corner")
        print("3. Check that text content is editable")
    else:
        print("\n💥 Test failed. Check error messages above.")
        sys.exit(1)