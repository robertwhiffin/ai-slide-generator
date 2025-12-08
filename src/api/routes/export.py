"""Export endpoints for PDF and PPTX generation."""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api.services.chat_service import get_chat_service
from src.services.html_to_pptx import HtmlToPptxConverterV3, PPTXConversionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportPPTXRequest(BaseModel):
    """Request to export slides to PPTX."""
    session_id: str  # Session ID to get slides from
    use_screenshot: bool = True  # Whether to use screenshot for charts


def build_slide_html(slide: dict, slide_deck: dict) -> str:
    """Build complete HTML for a single slide.
    
    Args:
        slide: Slide dictionary with html content
        slide_deck: Full slide deck with css, scripts, etc.
    
    Returns:
        Complete HTML string for the slide
    """
    external_scripts = slide_deck.get("external_scripts", [])
    scripts_html = "\n".join([
        f'    <script src="{src}"></script>' 
        for src in external_scripts
    ])
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{slide_deck.get("title", "Slide")} - Slide {slide.get("slide_id", "")}</title>
{scripts_html}
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    html, body {{
      width: 1280px;
      height: 720px;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: #ffffff;
      font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    }}
    {slide_deck.get("css", "")}
  </style>
</head>
<body>
{slide.get("html", "")}
  <script>
    try {{
      {slide_deck.get("scripts", "")}
    }} catch (error) {{
      console.debug('Chart initialization error:', error.message);
    }}
  </script>
</body>
</html>"""


@router.post("/pptx")
async def export_to_pptx(request: ExportPPTXRequest):
    """Export current slide deck to PowerPoint format.
    
    Args:
        request: Export request with options
    
    Returns:
        FileResponse with PPTX file
    
    Raises:
        HTTPException: 404 if no slides, 500 on conversion error
    """
    try:
        # Get current slide deck
        chat_service = get_chat_service()
        slide_deck = chat_service.get_slides(request.session_id)
        
        if not slide_deck or not slide_deck.get("slides"):
            raise HTTPException(status_code=404, detail="No slides available")
        
        logger.info(
            "Starting PPTX export",
            extra={
                "slide_count": len(slide_deck.get("slides", [])),
                "use_screenshot": request.use_screenshot
            }
        )
        
        # Initialize converter
        converter = HtmlToPptxConverterV3()
        
        # Prepare slides HTML
        slides_html = []
        html_files = []
        
        # Create temporary directory for HTML files (needed for screenshots)
        temp_dir = Path(tempfile.mkdtemp(prefix="pptx_export_"))
        
        try:
            for i, slide in enumerate(slide_deck.get("slides", [])):
                # Build complete HTML for each slide
                slide_html = build_slide_html(slide, slide_deck)
                slides_html.append(slide_html)
                
                # Create temporary HTML file for screenshot capture
                if request.use_screenshot:
                    html_file = temp_dir / f"slide_{i}.html"
                    html_file.write_text(slide_html, encoding='utf-8')
                    html_files.append(str(html_file))
                else:
                    html_files.append(None)
            
            # Create temporary output file
            output_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".pptx",
                prefix="export_"
            )
            output_path = output_file.name
            output_file.close()
            
            # Convert to PPTX
            await converter.convert_slide_deck(
                slides=slides_html,
                output_path=output_path,
                use_screenshot=request.use_screenshot,
                html_source_paths=html_files if request.use_screenshot else None
            )
            
            # Generate filename
            title = slide_deck.get("title", "slides")
            # Sanitize filename
            safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in title)
            filename = f"{safe_title.replace(' ', '_')}.pptx"
            
            logger.info("PPTX export completed", extra={"path": output_path, "filename": filename})
            
            # Cleanup function for temporary files
            def cleanup():
                try:
                    Path(output_path).unlink()
                    # Cleanup HTML files
                    for html_file in html_files:
                        if html_file and Path(html_file).exists():
                            Path(html_file).unlink()
                    # Cleanup temp directory
                    if temp_dir.exists():
                        temp_dir.rmdir()
                except Exception as e:
                    logger.warning("Failed to cleanup temp files", exc_info=True, extra={"error": str(e)})
            
            return FileResponse(
                path=output_path,
                filename=filename,
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                background=cleanup
            )
            
        except PPTXConversionError as e:
            logger.error("PPTX conversion failed", exc_info=True, extra={"error": str(e)})
            # Cleanup on error
            try:
                if temp_dir.exists():
                    for file in temp_dir.glob("*"):
                        file.unlink()
                    temp_dir.rmdir()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"PPTX conversion failed: {str(e)}")
        except Exception as e:
            logger.error("PPTX export failed", exc_info=True, extra={"error": str(e)})
            # Cleanup on error
            try:
                if temp_dir.exists():
                    for file in temp_dir.glob("*"):
                        file.unlink()
                    temp_dir.rmdir()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("PPTX export failed", exc_info=True, extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

