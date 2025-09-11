#!/usr/bin/env python3
"""PPTX to PDF converter using LibreOffice headless mode.

This script converts PowerPoint presentations to PDF format while preserving
all visuals, charts, and formatting. Uses LibreOffice's headless conversion
which is the #2 ranked approach for viewing PPTX content with visuals.
"""

import sys
import subprocess
import tempfile
from pathlib import Path


def convert_pptx_to_pdf(pptx_path: str, pdf_path: str = None) -> str:
    """Convert PPTX to PDF using LibreOffice headless mode.
    
    Args:
        pptx_path: Path to the input PPTX file
        pdf_path: Path for the output PDF (optional, defaults to same name with .pdf)
        
    Returns:
        Path to the generated PDF file
    """
    pptx_file = Path(pptx_path)
    
    if not pptx_file.exists():
        raise FileNotFoundError(f"❌ PPTX file not found: {pptx_path}")
    
    # Determine output path
    if pdf_path is None:
        pdf_file = pptx_file.with_suffix('.pdf')
    else:
        pdf_file = Path(pdf_path)
    
    # Create output directory if it doesn't exist
    pdf_file.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"🔄 Converting PPTX to PDF...")
    print(f"📄 Input:  {pptx_file}")
    print(f"📄 Output: {pdf_file}")
    
    try:
        # Use LibreOffice headless mode for conversion
        # --headless: run without GUI
        # --convert-to pdf: convert to PDF format
        # --outdir: specify output directory
        cmd = [
            'soffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', str(pdf_file.parent),
            str(pptx_file)
        ]
        
        print(f"🚀 Running: {' '.join(cmd)}")
        
        # Run the conversion
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # 60 second timeout
        )
        
        if result.returncode == 0:
            # LibreOffice creates PDF with same name as input but .pdf extension
            actual_pdf = pdf_file.parent / f"{pptx_file.stem}.pdf"
            
            # If we specified a different output name, rename it
            if actual_pdf != pdf_file:
                actual_pdf.rename(pdf_file)
            
            if pdf_file.exists():
                file_size = pdf_file.stat().st_size
                print(f"✅ Conversion successful!")
                print(f"📏 PDF size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
                return str(pdf_file)
            else:
                raise Exception("PDF file was not created")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            raise Exception(f"LibreOffice conversion failed: {error_msg}")
            
    except subprocess.TimeoutExpired:
        raise Exception("Conversion timed out after 60 seconds")
    except Exception as e:
        raise Exception(f"Conversion error: {str(e)}")


def view_pdf(pdf_path: str) -> None:
    """Open the PDF file for viewing."""
    pdf_file = Path(pdf_path)
    
    if not pdf_file.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        return
    
    try:
        # On macOS, use 'open' to view PDF
        subprocess.run(['open', str(pdf_file)], check=True)
        print(f"📖 Opening PDF in default viewer...")
    except subprocess.CalledProcessError:
        print(f"❌ Could not open PDF. File saved at: {pdf_path}")


def main():
    """Main function for command-line usage."""
    if len(sys.argv) < 2:
        print("Usage: python pptx_to_pdf.py <path_to_pptx_file> [output_pdf_path] [--view]")
        print("\nOptions:")
        print("  --view    Open the generated PDF after conversion")
        sys.exit(1)
    
    pptx_path = sys.argv[1]
    
    # Parse arguments
    view_after = '--view' in sys.argv
    if '--view' in sys.argv:
        sys.argv.remove('--view')
    
    pdf_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        # Convert PPTX to PDF
        result_pdf = convert_pptx_to_pdf(pptx_path, pdf_path)
        
        print(f"\n🎉 Success! PDF saved to: {result_pdf}")
        
        # Optionally view the PDF
        if view_after:
            view_pdf(result_pdf)
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()