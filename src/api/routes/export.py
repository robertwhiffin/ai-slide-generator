"""Export endpoints for PDF and PPTX generation."""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
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
    slide_id = slide.get("slide_id", "unknown")
    raw_slide_html = slide.get("html", "")
    external_scripts = slide_deck.get("external_scripts", [])
    deck_css = slide_deck.get("css", "")
    deck_scripts = slide_deck.get("scripts", "")
    
    # Clean up deck_scripts: remove any trailing extra IIFE closings
    # deck_scripts should be a series of (function() { ... })(); blocks
    # but sometimes there might be an extra })(); at the end
    if deck_scripts:
        import re
        # Remove any trailing })(); that might be extra
        deck_scripts = deck_scripts.rstrip()
        # Count opening and closing IIFEs
        iife_open = deck_scripts.count('(function() {')
        iife_close = deck_scripts.count('})();')
        
        # If there are more closings than openings, remove the extra ones
        if iife_close > iife_open:
            logger.warning(
                f"deck_scripts has {iife_close} IIFE closings but only {iife_open} openings. "
                "Removing extra closings.",
                extra={"slide_id": slide_id}
            )
            # Remove trailing })(); until counts match
            while iife_close > iife_open and deck_scripts.rstrip().endswith('})();'):
                deck_scripts = deck_scripts.rstrip()[:-6].rstrip()  # Remove })();
                iife_close -= 1
        
        # Validate deck_scripts doesn't contain incomplete try-catch blocks
        try_count = len(re.findall(r'\btry\s*\{', deck_scripts))
        catch_finally_count = len(re.findall(r'\b(catch|finally)\s*\(', deck_scripts))
        if try_count > catch_finally_count:
            logger.warning(
                f"deck_scripts contains {try_count} try blocks but only {catch_finally_count} catch/finally blocks. "
                "This may cause syntax errors.",
                extra={"slide_id": slide_id}
            )
    
    logger.info(
        "Building slide HTML",
        extra={
            "slide_id": slide_id,
            "raw_html_length": len(raw_slide_html),
            "external_scripts_count": len(external_scripts),
            "css_length": len(deck_css),
            "scripts_length": len(deck_scripts),
            "raw_html_preview": raw_slide_html[:500] + "..." if len(raw_slide_html) > 500 else raw_slide_html,
        }
    )
    
    scripts_html = "\n".join([
        f'    <script src="{src}" crossorigin="anonymous"></script>' 
        for src in external_scripts
    ])
    
    complete_html = f"""<!DOCTYPE html>
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
    {deck_css}
  </style>
</head>
<body>
{raw_slide_html}
  <script>
    // Optimized chart initialization for file:// protocol and Playwright
    (function() {{
      function initCharts() {{
        console.log('[CHART_INIT] Starting chart initialization process...');
        
        // Step 1: Wait for Chart.js to be fully loaded and ready
        function waitForChartJs(callback, maxAttempts = 200) {{
          let attempts = 0;
          const check = () => {{
            attempts++;
            // Check if Chart.js is loaded AND has the Chart constructor
            if (typeof Chart !== 'undefined' && typeof Chart.prototype !== 'undefined') {{
              console.log('[CHART_INIT] Chart.js loaded after ' + attempts + ' attempts');
              // Additional check: ensure Chart.js is fully initialized
              try {{
                // Test if Chart constructor works
                const testCanvas = document.createElement('canvas');
                testCanvas.width = 1;
                testCanvas.height = 1;
                const testCtx = testCanvas.getContext('2d');
                if (testCtx) {{
                  // Chart.js is ready, wait a bit more for stability
                  setTimeout(callback, 500);
                }} else {{
                  setTimeout(check, 50);
                }}
              }} catch (e) {{
                console.warn('[CHART_INIT] Chart.js test failed, retrying...', e);
                setTimeout(check, 100);
              }}
            }} else if (attempts < maxAttempts) {{
              setTimeout(check, 50); // Check more frequently
            }} else {{
              console.error('[CHART_INIT] Chart.js failed to load after ' + maxAttempts + ' attempts');
              // Try manual load as fallback
              const script = document.createElement('script');
              script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.js';
              script.crossOrigin = 'anonymous';
              script.onload = () => {{
                console.log('[CHART_INIT] Chart.js loaded manually, waiting for initialization...');
                setTimeout(callback, 1000);
              }};
              script.onerror = () => {{
                console.error('[CHART_INIT] Failed to load Chart.js manually');
                // Still try to proceed - maybe it's already loaded
                setTimeout(callback, 1000);
              }};
              document.head.appendChild(script);
            }}
          }};
          check();
        }}
        
        // Step 2: Initialize charts after Chart.js is ready
        waitForChartJs(() => {{
          try {{
            console.log('[CHART_INIT] Chart.js ready, setting up canvases...');
            
            // Find all canvas elements
            const canvases = document.querySelectorAll('canvas');
            console.log('[CHART_INIT] Found ' + canvases.length + ' canvas elements');
            
            if (canvases.length === 0) {{
              console.warn('[CHART_INIT] No canvas elements found');
              return;
            }}
            
            // Step 3: Set canvas dimensions BEFORE Chart.js initialization
            // This is critical - Chart.js needs non-zero dimensions
            canvases.forEach((canvas, idx) => {{
              const rect = canvas.getBoundingClientRect();
              const container = canvas.closest('.chart-container') || canvas.parentElement;
              
              // Determine dimensions from container, CSS, or defaults
              let targetWidth = 0;
              let targetHeight = 0;
              
              if (rect.width > 0 && rect.height > 0) {{
                targetWidth = Math.floor(rect.width);
                targetHeight = Math.floor(rect.height);
              }} else if (container) {{
                const containerRect = container.getBoundingClientRect();
                if (containerRect.width > 0 && containerRect.height > 0) {{
                  targetWidth = Math.floor(containerRect.width);
                  targetHeight = Math.floor(containerRect.height);
                }}
              }}
              
              // Use defaults if still no dimensions
              if (targetWidth === 0 || targetHeight === 0) {{
                targetWidth = 800;
                targetHeight = 400;
                console.log('[CHART_INIT] Using default dimensions for canvas ' + idx);
              }}
              
              // Set dimensions explicitly (Chart.js will respect these)
              canvas.width = targetWidth;
              canvas.height = targetHeight;
              
              // Also set CSS dimensions to match (for responsive behavior)
              canvas.style.width = targetWidth + 'px';
              canvas.style.height = targetHeight + 'px';
              
              console.log('[CHART_INIT] Canvas ' + idx + ' (' + (canvas.id || 'unnamed') + '): ' + 
                         targetWidth + 'x' + targetHeight + ' (rect: ' + rect.width + 'x' + rect.height + ')');
            }});
            
            // Step 4: Wait for layout to settle, then initialize charts
            // Use requestAnimationFrame for better timing
            requestAnimationFrame(() => {{
              setTimeout(() => {{
                try {{
                  console.log('[CHART_INIT] Executing chart scripts...');
                  
                  // Execute chart initialization scripts
                  // These are already IIFE-wrapped, so execute directly
                  {deck_scripts}
                  
                  console.log('[CHART_INIT] Chart scripts executed successfully');
                  
                  // Step 5: Verify charts are rendering
                  let checkCount = 0;
                  const maxChecks = 30; // More checks for reliability
                  const checkInterval = setInterval(() => {{
                    checkCount++;
                    const canvasesAfter = document.querySelectorAll('canvas');
                    console.log('[CHART_INIT] Check ' + checkCount + ': ' + canvasesAfter.length + ' canvases');
                    
                    let renderedCount = 0;
                    let allReady = true;
                    
                    canvasesAfter.forEach((canvas, index) => {{
                      try {{
                        // Verify canvas has dimensions
                        if (canvas.width === 0 || canvas.height === 0) {{
                          console.warn('[CHART_INIT] Canvas ' + index + ' has zero dimensions, fixing...');
                          const rect = canvas.getBoundingClientRect();
                          if (rect.width > 0 && rect.height > 0) {{
                            canvas.width = Math.floor(rect.width);
                            canvas.height = Math.floor(rect.height);
                          }} else {{
                            canvas.width = 800;
                            canvas.height = 400;
                          }}
                          allReady = false;
                          return;
                        }}
                        
                        // Check if canvas has content
                        const ctx = canvas.getContext('2d');
                        if (!ctx) {{
                          console.warn('[CHART_INIT] Canvas ' + index + ' context unavailable');
                          allReady = false;
                          return;
                        }}
                        
                        // Sample a larger area for more reliable detection
                        const sampleWidth = Math.min(canvas.width, 400);
                        const sampleHeight = Math.min(canvas.height, 400);
                        const imageData = ctx.getImageData(0, 0, sampleWidth, sampleHeight);
                        const data = imageData.data;
                        let pixelCount = 0;
                        for (let i = 3; i < data.length; i += 4) {{
                          if (data[i] > 0) {{
                            pixelCount++;
                          }}
                        }}
                        
                        const hasContent = pixelCount > 100; // Lower threshold for faster detection
                        console.log('[CHART_INIT] Canvas ' + index + ' (' + (canvas.id || 'unnamed') + 
                                   '): ' + pixelCount + ' pixels, ready: ' + hasContent);
                        
                        if (hasContent) {{
                          renderedCount++;
                        }} else {{
                          allReady = false;
                        }}
                      }} catch (e) {{
                        console.warn('[CHART_INIT] Error checking canvas ' + index + ':', e);
                        allReady = false;
                      }}
                    }});
                    
                    console.log('[CHART_INIT] Progress: ' + renderedCount + '/' + canvasesAfter.length + ' charts rendered');
                    
                    if (allReady && renderedCount === canvasesAfter.length && canvasesAfter.length > 0) {{
                      console.log('[CHART_INIT] All charts are ready!');
                      clearInterval(checkInterval);
                    }} else if (checkCount >= maxChecks) {{
                      console.warn('[CHART_INIT] Max checks reached (' + maxChecks + '), ' + 
                                 renderedCount + '/' + canvasesAfter.length + ' charts rendered');
                      clearInterval(checkInterval);
                    }}
                  }}, 600); // Check every 600ms
                  
                }} catch (scriptError) {{
                  console.error('[CHART_INIT] Error executing chart scripts:', scriptError);
                  console.error('[CHART_INIT] Stack:', scriptError.stack);
                }}
              }}, 200); // Short delay after dimensions are set
            }});
            
          }} catch (error) {{
            console.error('[CHART_INIT] Chart initialization error:', error);
            console.error('[CHART_INIT] Stack:', error.stack);
          }}
        }});
      }}
      
      // Start initialization when DOM is ready
      if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', initCharts);
      }} else {{
        // DOM already ready, start immediately
        initCharts();
      }}
    }})();
  </script>
</body>
</html>"""
    
    logger.info(
        "Built complete slide HTML",
        extra={
            "slide_id": slide_id,
            "complete_html_length": len(complete_html),
            "includes_external_scripts": len(external_scripts) > 0,
            "includes_css": len(deck_css) > 0,
            "includes_scripts": len(deck_scripts) > 0,
            "complete_html_preview": complete_html[:1000] + "..." if len(complete_html) > 1000 else complete_html,
        }
    )
    
    return complete_html


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
    # Log to both logger and print to ensure visibility
    log_msg = f"PPTX export request received - session_id: {request.session_id}, use_screenshot: {request.use_screenshot}"
    logger.info(log_msg)
    print(f"[EXPORT] {log_msg}")  # Also print to stdout for uvicorn to capture
    
    try:
        # Get current slide deck
        chat_service = get_chat_service()
        slide_deck = chat_service.get_slides(request.session_id)
        
        if not slide_deck or not slide_deck.get("slides"):
            raise HTTPException(status_code=404, detail="No slides available")
        
        slide_count = len(slide_deck.get("slides", []))
        log_msg = (
            f"Starting PPTX export - slides: {slide_count}, "
            f"title: {slide_deck.get('title')}, "
            f"has_css: {bool(slide_deck.get('css'))}, "
            f"has_scripts: {bool(slide_deck.get('scripts'))}, "
            f"external_scripts: {len(slide_deck.get('external_scripts', []))}"
        )
        logger.info(log_msg)
        print(f"[EXPORT] {log_msg}")  # Also print to stdout
        
        # Log slide deck structure
        slides_info = [
            {
                "slide_id": slide.get("slide_id"),
                "html_length": len(slide.get("html", "")),
                "html_preview": slide.get("html", "")[:200] + "..." if len(slide.get("html", "")) > 200 else slide.get("html", "")
            }
            for slide in slide_deck.get("slides", [])
        ]
        logger.info("Slide deck structure for export", extra={"slides": slides_info})
        print(f"[EXPORT] Slide deck structure: {len(slides_info)} slides")
        for i, slide_info in enumerate(slides_info):
            print(f"[EXPORT]   Slide {i}: {slide_info['slide_id']}, HTML length: {slide_info['html_length']}, preview: {slide_info['html_preview']}")
        
        # Initialize converter
        converter = HtmlToPptxConverterV3()
        
        # Prepare slides HTML
        slides_html = []
        html_files = []
        
        # Create temporary directory for HTML files (needed for screenshots)
        temp_dir = Path(tempfile.mkdtemp(prefix="pptx_export_"))
        logger.info("Created temp directory for export", extra={"temp_dir": str(temp_dir)})
        
        try:
            for i, slide in enumerate(slide_deck.get("slides", [])):
                slide_id = slide.get("slide_id", f"slide_{i}")
                raw_html = slide.get("html", "")
                log_msg = f"Building HTML for slide {i} ({slide_id}) - raw HTML length: {len(raw_html)}"
                logger.info(log_msg, extra={"slide_index": i, "slide_id": slide_id, "raw_html_length": len(raw_html)})
                print(f"[EXPORT] {log_msg}")
                print(f"[EXPORT] Raw HTML preview: {raw_html[:500]}{'...' if len(raw_html) > 500 else ''}")
                
                # Build complete HTML for each slide
                slide_html = build_slide_html(slide, slide_deck)
                html_length = len(slide_html)
                slides_html.append(slide_html)
                
                log_msg = (
                    f"Built complete HTML for slide {i} ({slide_id}) - "
                    f"length: {html_length}, "
                    f"has_external_scripts: {len(slide_deck.get('external_scripts', [])) > 0}, "
                    f"has_scripts: {bool(slide_deck.get('scripts'))}"
                )
                logger.info(log_msg, extra={"slide_index": i, "slide_id": slide_id, "complete_html_length": html_length})
                print(f"[EXPORT] {log_msg}")
                print(f"[EXPORT] Complete HTML preview: {slide_html[:1000]}{'...' if html_length > 1000 else ''}")
                
                # Create temporary HTML file for screenshot capture
                if request.use_screenshot:
                    html_file = temp_dir / f"slide_{i}.html"
                    html_file.write_text(slide_html, encoding='utf-8')
                    html_files.append(str(html_file))
                    
                    # Verify file was written and contains Chart.js
                    file_size = html_file.stat().st_size
                    has_chart_js = 'chart.js' in slide_html.lower() or 'cdn.jsdelivr.net/npm/chart' in slide_html.lower()
                    has_canvas = '<canvas' in slide_html.lower()
                    has_scripts = '<script' in slide_html.lower()
                    
                    logger.info(
                        "Created HTML file for screenshot",
                        extra={
                            "slide_index": i,
                            "html_file": str(html_file),
                            "file_size": file_size,
                            "has_chart_js": has_chart_js,
                            "has_canvas": has_canvas,
                            "has_scripts": has_scripts,
                        }
                    )
                    print(
                        f"[EXPORT] Created HTML file for slide {i}: {html_file}, "
                        f"size: {file_size} bytes, Chart.js: {has_chart_js}, Canvas: {has_canvas}, Scripts: {has_scripts}"
                    )
                    
                    if not has_chart_js:
                        logger.warning(f"HTML file for slide {i} does not contain Chart.js CDN link")
                        print(f"[EXPORT] WARNING: HTML file for slide {i} missing Chart.js!")
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
            
            # Log summary before conversion
            logger.info(
                "Starting PPTX conversion",
                extra={
                    "total_slides": len(slides_html),
                    "html_lengths": [len(html) for html in slides_html],
                    "total_html_size": sum(len(html) for html in slides_html),
                    "use_screenshot": request.use_screenshot,
                    "html_files_count": len([f for f in html_files if f]),
                    "output_path": output_path,
                }
            )
            
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
            
            # Use BackgroundTasks for cleanup
            background_tasks = BackgroundTasks()
            background_tasks.add_task(cleanup)
            
            return FileResponse(
                path=output_path,
                filename=filename,
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                background=background_tasks
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


