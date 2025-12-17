#!/usr/bin/env python3

import importlib.util
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from databricks.sdk import WorkspaceClient
from pptx import Presentation
from pptx.util import Inches

from src.services.pptx_prompts_defaults import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT_TEMPLATE,
    DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT,
    DEFAULT_MULTI_SLIDE_USER_PROMPT,
)

logger = logging.getLogger(__name__)


class PPTXConversionError(Exception):
    """Raised when PPTX conversion fails."""
    pass


class HtmlToPptxConverterV3:
    """V3 converter using maximum LLM flexibility approach.
    
    This converter uses an LLM to analyze HTML and generate Python code
    that creates PowerPoint slides. This approach provides maximum flexibility
    and handles diverse layouts automatically.
    
    Attributes:
        model_endpoint: LLM model endpoint name
        ws_client: Databricks workspace client
        llm_client: OpenAI-compatible client for LLM calls
    """
    
    # Model configuration
    DEFAULT_MODEL = "databricks-claude-sonnet-4-5"
    

    def __init__(
        self,
        workspace_client: Optional[WorkspaceClient] = None,
        model_endpoint: Optional[str] = None,
    ):
        """Initialize V3 converter.
        
        Args:
            workspace_client: Databricks client (optional, uses singleton if not provided)
            model_endpoint: LLM model name (default: databricks-claude-sonnet-4-5)
        """
        self.model_endpoint = model_endpoint or self.DEFAULT_MODEL
        
        # Use provided client or get singleton from databricks_client
        if workspace_client:
            self.ws_client = workspace_client
        else:
            from src.core.databricks_client import get_databricks_client
            self.ws_client = get_databricks_client()
        
        # Initialize OpenAI-compatible client for LLM calls
        self.llm_client = self.ws_client.serving_endpoints.get_open_ai_client()
        
        # Load default prompts
        self.SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
        self.USER_PROMPT_TEMPLATE = DEFAULT_USER_PROMPT_TEMPLATE
        self.MULTI_SLIDE_SYSTEM_PROMPT = DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT
        self.MULTI_SLIDE_USER_PROMPT = DEFAULT_MULTI_SLIDE_USER_PROMPT
        
        logger.info(
            "V3 Converter initialized",
            extra={"model": self.model_endpoint}
        )
    
    async def convert_html_to_pptx(
        self,
        html_str: str,
        output_path: str,
        use_screenshot: bool = True,
        html_source_path: Optional[str] = None
    ) -> str:
        """Convert single HTML slide to PowerPoint.
        
        Args:
            html_str: HTML content
            output_path: Path to save PPTX
            use_screenshot: Whether to capture and use screenshot
            html_source_path: Path to HTML file (for screenshot)
        
        Returns:
            Path to created PPTX file
        
        Raises:
            PPTXConversionError: If conversion fails
        """
        logger.info("Converting single HTML to PowerPoint")
        
        # 1. Setup working directory
        work_dir = Path(tempfile.mkdtemp(prefix="v3_convert_"))
        assets_dir = work_dir / "assets"
        assets_dir.mkdir()
        
        # 2. Capture chart screenshots if requested
        chart_images = []
        if use_screenshot and html_source_path:
            chart_images = await self._capture_screenshot(html_source_path, str(assets_dir))
            if chart_images:
                logger.info("Chart screenshots captured", extra={"chart_count": len(chart_images), "charts": chart_images})
            else:
                logger.warning("Chart screenshot capture failed, continuing without them")
        
        # 3. Call LLM to generate converter code
        logger.info("Calling LLM to generate converter code")
        converter_code = await self._generate_converter_code(
            html_str,
            chart_images=chart_images
        )
        
        if not converter_code:
            raise PPTXConversionError("Failed to generate converter code from LLM")
        
        # 4. Execute generated code
        logger.info("Executing generated converter")
        self._execute_single_slide_converter(
            converter_code,
            html_str,
            output_path,
            str(assets_dir)
        )
        
        logger.info("PowerPoint created", extra={"path": output_path})
        return output_path
    
    async def convert_slide_deck(
        self,
        slides: List[str],
        output_path: str,
        use_screenshot: bool = True,
        html_source_paths: Optional[List[str]] = None
    ) -> str:
        """Convert multiple HTML slides to PowerPoint deck.
        
        Args:
            slides: List of HTML strings
            output_path: Path to save PPTX
            use_screenshot: Whether to capture screenshots
            html_source_paths: Paths to HTML files (for screenshots)
        
        Returns:
            Path to created PPTX file
        
        Raises:
            PPTXConversionError: If conversion fails
        """
        log_msg = (
            f"Converting {len(slides)} slides to PowerPoint - "
            f"total HTML size: {sum(len(html) for html in slides)}, "
            f"use_screenshot: {use_screenshot}"
        )
        logger.info(log_msg)
        print(f"[PPTX_CONVERTER] {log_msg}")
        
        # Log first 1000 chars of each slide HTML for debugging
        for i, html in enumerate(slides):
            log_msg = (
                f"Received HTML for slide {i} - "
                f"length: {len(html)}, "
                f"has_script: {'<script' in html.lower()}, "
                f"has_style: {'<style' in html.lower()}, "
                f"has_canvas: {'<canvas' in html.lower()}"
            )
            logger.info(log_msg, extra={"slide_index": i, "html_length": len(html)})
            print(f"[PPTX_CONVERTER] {log_msg}")
            print(f"[PPTX_CONVERTER] HTML preview: {html[:1000]}{'...' if len(html) > 1000 else ''}")
        
        # Create presentation
        prs = Presentation()
        prs.slide_width = Inches(10)
        prs.slide_height = Inches(7.5)
        
        # Process each slide
        for i, html_str in enumerate(slides, 1):
            log_msg = f"Processing slide {i}/{len(slides)} - HTML length: {len(html_str)}"
            logger.info(log_msg, extra={"slide_number": i, "total_slides": len(slides), "html_length": len(html_str)})
            print(f"[PPTX_CONVERTER] {log_msg}")
            
            # Setup for this slide
            html_path = html_source_paths[i-1] if html_source_paths and i-1 < len(html_source_paths) else None
            logger.info(
                "Slide processing setup",
                extra={
                    "slide_number": i,
                    "html_path": html_path,
                    "use_screenshot": use_screenshot,
                    "html_length": len(html_str),
                }
            )
            
            # Create slide and add content using V3 approach
            await self._add_slide_to_presentation(
                prs,
                html_str,
                use_screenshot=use_screenshot,
                html_source_path=html_path,
                slide_number=i
            )
        
        # Save presentation
        prs.save(output_path)
        logger.info(
            "PowerPoint deck created",
            extra={"path": output_path, "slide_count": len(slides)}
        )
        return output_path
    
    async def _add_slide_to_presentation(
        self,
        prs: Presentation,
        html_str: str,
        use_screenshot: bool,
        html_source_path: Optional[str],
        slide_number: int
    ) -> None:
        """Add a slide to existing presentation using V3 approach.
        
        Args:
            prs: Presentation object to add slide to
            html_str: HTML content for the slide
            use_screenshot: Whether to capture and use screenshot
            html_source_path: Path to HTML file (for screenshot capture)
            slide_number: Slide number for logging purposes
        """
        # 1. Setup working directory for this slide
        work_dir = Path(tempfile.mkdtemp(prefix=f"v3_slide_{slide_number}_"))
        assets_dir = work_dir / "assets"
        assets_dir.mkdir()
        
        # 2. Capture chart screenshots if requested
        chart_images = []
        if use_screenshot and html_source_path:
            logger.info(
                "Capturing chart screenshots for slide",
                extra={
                    "slide_number": slide_number,
                    "html_source_path": html_source_path,
                    "assets_dir": str(assets_dir)
                }
            )
            print(f"[PPTX_CONVERTER] Capturing chart screenshots for slide {slide_number} from {html_source_path}")
            chart_images = await self._capture_screenshot(html_source_path, str(assets_dir))
            if chart_images:
                logger.info(
                    "Chart screenshots captured successfully",
                    extra={
                        "slide_number": slide_number,
                        "chart_count": len(chart_images),
                        "chart_files": chart_images
                    }
                )
                print(f"[PPTX_CONVERTER] Captured {len(chart_images)} chart screenshots for slide {slide_number}: {chart_images}")
            else:
                logger.warning("No chart screenshots captured", extra={"slide_number": slide_number})
                print(f"[PPTX_CONVERTER] WARNING: No chart screenshots captured for slide {slide_number}")
        
        # 3. Call LLM to generate code for adding this slide
        logger.debug("Calling LLM for slide", extra={"slide_number": slide_number})
        slide_code = await self._generate_slide_adder_code(
            html_str,
            chart_images=chart_images
        )
        
        if not slide_code:
            logger.warning(
                "Failed to generate code for slide, skipping",
                extra={"slide_number": slide_number}
            )
            return
        
        # 4. Execute generated code to add slide
        logger.debug("Adding slide to presentation", extra={"slide_number": slide_number})
        self._execute_slide_adder(
            slide_code,
            prs,
            html_str,
            str(assets_dir)
        )
        
        logger.debug("Slide added", extra={"slide_number": slide_number})
    
    async def _generate_converter_code(
        self,
        html_str: str,
        chart_images: list[str]
    ) -> Optional[str]:
        """Call LLM to generate converter code for single slide.
        
        Args:
            html_str: HTML content to convert
            chart_images: List of chart image filenames (e.g., ['chart_0.png', 'chart_1.png'])
        
        Returns:
            Generated Python code or None if generation fails
        """
        logger.debug(
            "Generating converter code",
            extra={
                "original_html_length": len(html_str),
                "chart_images": chart_images,
                "chart_count": len(chart_images),
            }
        )
        
        # Truncate HTML if too long
        html_content = self._truncate_html(html_str)
        
        logger.debug(
            "HTML truncated for LLM",
            extra={
                "original_length": len(html_str),
                "truncated_length": len(html_content),
                "was_truncated": len(html_content) < len(html_str),
                "truncated_preview": html_content[:500] + "..." if len(html_content) > 500 else html_content,
            }
        )
        
        screenshot_note = ""
        if chart_images:
            chart_files_str = ", ".join(chart_images)
            screenshot_note = (
                f"Chart images exist: {chart_files_str}. "
                f"Use: slide.shapes.add_picture(os.path.join(assets_dir, '{chart_images[0]}'), left, top, width, height). "
                f"Match chart_N.png to Nth canvas. Position at canvas location in HTML."
            )
        else:
            screenshot_note = "No chart images. Extract Chart.js data from <script> tags. Only use data from HTML."
        
        prompt = self.USER_PROMPT_TEMPLATE.format(
            html_content=html_content,
            screenshot_note=screenshot_note
        )
        
        return await self._call_llm(self.SYSTEM_PROMPT, prompt)
    
    async def _generate_slide_adder_code(
        self,
        html_str: str,
        chart_images: list[str]
    ) -> Optional[str]:
        """Call LLM to generate code for adding slide to existing presentation.
        
        Args:
            html_str: HTML content to convert
            chart_images: List of chart image filenames (e.g., ['chart_0.png', 'chart_1.png'])
        
        Returns:
            Generated Python code or None if generation fails
        """
        logger.debug(
            "Generating slide adder code",
            extra={
                "original_html_length": len(html_str),
                "chart_images": chart_images,
                "chart_count": len(chart_images),
            }
        )
        
        # Truncate HTML if too long
        html_content = self._truncate_html(html_str)
        
        logger.debug(
            "HTML truncated for LLM (slide adder)",
            extra={
                "original_length": len(html_str),
                "truncated_length": len(html_content),
                "was_truncated": len(html_content) < len(html_str),
                "truncated_preview": html_content[:500] + "..." if len(html_content) > 500 else html_content,
            }
        )
        
        screenshot_note = ""
        if chart_images:
            chart_files_str = ", ".join(chart_images)
            screenshot_note = (
                f"Chart images exist: {chart_files_str}. "
                f"Use: slide.shapes.add_picture(os.path.join(assets_dir, '{chart_images[0]}'), left, top, width, height). "
                f"Match chart_N.png to Nth canvas. Position at canvas location in HTML."
            )
        else:
            screenshot_note = "No chart images. Extract Chart.js data from <script> tags. Only use data from HTML."
        
        prompt = self.MULTI_SLIDE_USER_PROMPT.format(
            html_content=html_content,
            screenshot_note=screenshot_note
        )
        
        return await self._call_llm(self.MULTI_SLIDE_SYSTEM_PROMPT, prompt)
    
    async def _call_llm(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call Databricks LLM to generate code.
        
        Args:
            system_prompt: System prompt for LLM
            user_prompt: User prompt with HTML content
        
        Returns:
            Generated Python code or None if call fails
        """
        logger.debug(
            "Calling LLM to generate converter code",
            extra={
                "model": self.model_endpoint,
                "system_prompt_length": len(system_prompt),
                "user_prompt_length": len(user_prompt),
                "user_prompt_preview": user_prompt[:500] + "..." if len(user_prompt) > 500 else user_prompt,
            }
        )
        
        try:
            response = self.llm_client.chat.completions.create(
                model=self.model_endpoint,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,  # Some creativity but not too much
            )
            
            code = response.choices[0].message.content
            
            logger.debug(
                "LLM response received",
                extra={
                    "code_length": len(code) if code else 0,
                    "code_preview": code[:500] + "..." if code and len(code) > 500 else code,
                }
            )
            
            # Extract code from markdown if wrapped
            if '```python' in code:
                match = re.search(r'```python\n(.*?)```', code, re.DOTALL)
                if match:
                    code = match.group(1)
            elif '```' in code:
                match = re.search(r'```\n(.*?)```', code, re.DOTALL)
                if match:
                    code = match.group(1)
            
            return code
            
        except Exception as e:
            logger.error("LLM call failed", exc_info=True, extra={"error": str(e)})
            return None
    
    def _ensure_playwright_browsers(self) -> None:
        """Ensure Playwright browser binaries are installed.
        
        This method checks if Chromium is installed and installs it if missing.
        Uses subprocess to call Playwright's install command programmatically.
        """
        try:
            import subprocess
            import sys
            
            # First, try to verify if Chromium is already installed
            # by attempting to launch it (quick check)
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                logger.debug("Playwright Chromium is already installed")
                return
            except Exception:
                # Chromium not installed or launch failed, proceed to install
                pass
            
            # Install Chromium using subprocess (most reliable method)
            logger.info("Playwright browsers not found, installing Chromium...")
            print("[PLAYWRIGHT] Installing Chromium browser binaries (this may take a minute)...")
            
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                logger.info("Playwright Chromium installed successfully")
                print("[PLAYWRIGHT] ✓ Chromium installed successfully")
            else:
                error_msg = result.stderr or result.stdout
                logger.warning(f"Playwright install had issues: {error_msg}")
                print(f"[PLAYWRIGHT] ⚠️  Install warning: {error_msg}")
                # Don't raise - allow code to continue, it will fail later with a clearer error
                    
        except ImportError:
            logger.error("Playwright not installed. Install with: pip install playwright")
            print("[PLAYWRIGHT] ❌ Playwright package not installed")
            # Don't raise - allow code to continue, it will fail later with a clearer error
        except Exception as e:
            # Check if it's a timeout error
            if "TimeoutExpired" in str(type(e)) or "timeout" in str(e).lower():
                logger.error("Playwright install timed out after 5 minutes")
                print("[PLAYWRIGHT] ❌ Install timed out")
            else:
                logger.error(f"Error ensuring Playwright browsers: {e}", exc_info=True)
                print(f"[PLAYWRIGHT] ❌ Error: {e}")
            # Don't raise - allow code to continue, it will fail later with a clearer error
    
    async def _capture_screenshot(self, html_path: str, assets_dir: str) -> list[str]:
        """Capture screenshots of chart canvas elements from HTML using Playwright (async).
        
        Args:
            html_path: Path to HTML file
            assets_dir: Directory to save chart screenshots
        
        Returns:
            List of paths to captured chart images (e.g., ['chart_0.png', 'chart_1.png'])
        """
        try:
            # Ensure browsers are installed before attempting to use Playwright
            self._ensure_playwright_browsers()
            
            from playwright.async_api import async_playwright
            
            logger.info(
                "Starting screenshot capture",
                extra={"html_path": html_path, "assets_dir": assets_dir}
            )
            print(f"[SCREENSHOT] Capturing screenshot from {html_path}")
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                
                # Capture console logs for debugging
                console_logs = []
                page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
                
                file_url = f"file://{os.path.abspath(html_path)}"
                logger.debug(f"Loading HTML file: {file_url}")
                print(f"[SCREENSHOT] Loading HTML: {file_url}")
                
                await page.goto(file_url, wait_until="networkidle", timeout=30000)
                
                # Wait for page to be fully loaded
                await page.wait_for_load_state("networkidle", timeout=10000)
                await page.wait_for_timeout(3000)  # Wait for initial rendering and scripts
                
                # Log console messages
                if console_logs:
                    logger.info(f"Console logs: {console_logs[-10:]}")  # Last 10 logs
                    print(f"[SCREENSHOT] Console logs: {console_logs[-10:]}")
                
                # Check if Chart.js is loaded
                chart_js_loaded = await page.evaluate("""() => {
                    return typeof Chart !== 'undefined';
                }""")
                
                logger.info(f"Chart.js loaded: {chart_js_loaded}")
                print(f"[SCREENSHOT] Chart.js loaded: {chart_js_loaded}")
                
                # Wait for canvases to be rendered and charts to be initialized
                canvas_count = await page.evaluate("""() => {
                    return document.querySelectorAll('canvas').length;
                }""")
                
                logger.info(f"Found {canvas_count} canvas elements")
                print(f"[SCREENSHOT] Found {canvas_count} canvas elements")
                
                # CRITICAL: Set canvas dimensions explicitly in Playwright BEFORE chart scripts run
                # This ensures canvases have dimensions before Chart.js tries to render
                if canvas_count > 0:
                    # First, wait a bit for HTML scripts to potentially set dimensions
                    await page.wait_for_timeout(2000)
                    
                    # Then check and set dimensions if needed
                    canvas_info = await page.evaluate("""() => {
                        const canvases = document.querySelectorAll('canvas');
                        const info = [];
                        canvases.forEach((canvas, idx) => {
                            const rect = canvas.getBoundingClientRect();
                            const currentWidth = canvas.width;
                            const currentHeight = canvas.height;
                            
                            if (currentWidth === 0 || currentHeight === 0) {
                                if (rect.width > 0 && rect.height > 0) {
                                    canvas.width = rect.width;
                                    canvas.height = rect.height;
                                } else {
                                    // Use container dimensions or defaults
                                    const container = canvas.closest('.chart-container') || canvas.parentElement;
                                    if (container) {
                                        const containerRect = container.getBoundingClientRect();
                                        if (containerRect.width > 0 && containerRect.height > 0) {
                                            canvas.width = containerRect.width;
                                            canvas.height = containerRect.height;
                                        } else {
                                            canvas.width = 800;
                                            canvas.height = 400;
                                        }
                                    } else {
                                        canvas.width = 800;
                                        canvas.height = 400;
                                    }
                                }
                            }
                            
                            info.push({
                                id: canvas.id || 'unnamed',
                                width: canvas.width,
                                height: canvas.height,
                                rectWidth: rect.width,
                                rectHeight: rect.height
                            });
                        });
                        return info;
                    }""")
                    
                    logger.info(f"Canvas dimensions set: {canvas_info}")
                    print(f"[SCREENSHOT] Canvas dimensions: {canvas_info}")
                    
                    # Now trigger chart initialization if it hasn't happened
                    # Check if charts are already initialized
                    charts_initialized = await page.evaluate("""() => {
                        const canvases = document.querySelectorAll('canvas');
                        for (let canvas of canvases) {
                            const ctx = canvas.getContext('2d');
                            if (ctx) {
                                try {
                                    const imageData = ctx.getImageData(0, 0, 10, 10);
                                    const data = imageData.data;
                                    let hasContent = false;
                                    for (let i = 3; i < data.length; i += 4) {
                                        if (data[i] > 0) {
                                            hasContent = true;
                                            break;
                                        }
                                    }
                                    if (hasContent) return true;
                                } catch (e) {
                                    // Canvas might not be ready
                                }
                            }
                        }
                        return false;
                    }""")
                    
                    if not charts_initialized:
                        # Charts haven't rendered yet, wait for HTML scripts to run
                        logger.info("Charts not yet initialized, waiting for HTML scripts...")
                        print("[SCREENSHOT] Charts not yet initialized, waiting for HTML scripts...")
                        await page.wait_for_timeout(3000)  # Wait for chart scripts to execute
                
                if canvas_count > 0:
                    # Wait for all canvases to be ready
                    try:
                        await page.wait_for_selector('canvas', timeout=10000)
                        
                        # Wait for Chart.js to initialize charts (multiple attempts with longer waits)
                        max_attempts = 15
                        charts_ready = False
                        
                        for attempt in range(max_attempts):
                            await page.wait_for_timeout(1500)  # Wait 1.5 seconds between checks
                            
                            # Verify charts are actually drawn (check if canvas has content)
                            charts_ready = await page.evaluate("""() => {
                                const canvases = document.querySelectorAll('canvas');
                                if (canvases.length === 0) return false;
                                
                                let allReady = true;
                                for (let canvas of canvases) {
                                    // Check if canvas has valid dimensions
                                    if (canvas.width === 0 || canvas.height === 0) {
                                        console.log('Canvas has zero dimensions');
                                        allReady = false;
                                        continue;
                                    }
                                    
                                    const ctx = canvas.getContext('2d');
                                    if (!ctx) {
                                        console.log('Canvas context not available');
                                        allReady = false;
                                        continue;
                                    }
                                    
                                    // Check a larger sample area (up to 200x200px)
                                    const sampleWidth = Math.min(canvas.width, 200);
                                    const sampleHeight = Math.min(canvas.height, 200);
                                    const imageData = ctx.getImageData(0, 0, sampleWidth, sampleHeight);
                                    const data = imageData.data;
                                    
                                    // Check if canvas has any non-transparent pixels
                                    let hasContent = false;
                                    let pixelCount = 0;
                                    for (let i = 3; i < data.length; i += 4) {
                                        if (data[i] > 0) {  // Alpha channel > 0 means visible
                                            hasContent = true;
                                            pixelCount++;
                                        }
                                    }
                                    
                                    // Need at least 50 pixels to be drawn (charts should have more)
                                    if (!hasContent || pixelCount < 50) {
                                        console.log('Canvas ' + canvas.id + ' has only ' + pixelCount + ' pixels');
                                        allReady = false;
                                    } else {
                                        console.log('Canvas ' + canvas.id + ' is ready with ' + pixelCount + ' pixels');
                                    }
                                }
                                return allReady;
                    }""")
                    
                            if charts_ready:
                                logger.info(f"Charts are ready after {attempt + 1} attempts")
                                print(f"[SCREENSHOT] Charts are ready after {attempt + 1} attempts")
                                # Wait one more second to ensure everything is fully rendered
                                await page.wait_for_timeout(1000)
                                break
                            else:
                                logger.debug(f"Charts not ready yet, attempt {attempt + 1}/{max_attempts}")
                                print(f"[SCREENSHOT] Charts not ready yet, attempt {attempt + 1}/{max_attempts}")
                        
                        if not charts_ready:
                            logger.warning("Charts may not be fully rendered, but proceeding with screenshot")
                            print("[SCREENSHOT] WARNING: Charts may not be fully rendered, proceeding anyway")
                            # Wait a bit more before capturing
                            await page.wait_for_timeout(3000)
                    except Exception as e:
                        logger.warning(f"Error waiting for canvas: {e}")
                        print(f"[SCREENSHOT] Warning waiting for canvas: {e}")
                        # Still proceed with screenshot even if check fails
                        await page.wait_for_timeout(4000)
                
                # Capture individual chart canvas elements instead of full slide
                chart_images = []
                
                if canvas_count > 0:
                    logger.info(f"Capturing {canvas_count} chart canvas elements")
                    print(f"[SCREENSHOT] Capturing {canvas_count} chart canvas elements")
                    
                    # Get canvas information including positions
                    canvas_data = await page.evaluate("""() => {
                        const canvases = document.querySelectorAll('canvas');
                        const data = [];
                        canvases.forEach((canvas, idx) => {
                            const rect = canvas.getBoundingClientRect();
                            data.push({
                                index: idx,
                                id: canvas.id || `chart_${idx}`,
                                x: Math.floor(rect.x),
                                y: Math.floor(rect.y),
                                width: Math.floor(rect.width),
                                height: Math.floor(rect.height),
                                canvasWidth: canvas.width,
                                canvasHeight: canvas.height
                            });
                        });
                        return data;
                    }""")
                    
                    logger.info(f"Canvas data: {canvas_data}")
                    print(f"[SCREENSHOT] Canvas data: {canvas_data}")
                    
                    # Capture each canvas individually
                    for canvas_info in canvas_data:
                        canvas_id = canvas_info['id']
                        canvas_index = canvas_info['index']
                        
                        # Use canvas ID if available, otherwise use index
                        if canvas_id and canvas_id != f'chart_{canvas_index}':
                            filename = f"chart_{canvas_id}.png"
                        else:
                            filename = f"chart_{canvas_index}.png"
                        
                        chart_path = Path(assets_dir) / filename
                        
                        try:
                            # Capture just the canvas element using element screenshot
                            canvas_element = await page.query_selector(f'canvas:nth-of-type({canvas_index + 1})')
                            
                            if canvas_element:
                                await canvas_element.screenshot(path=str(chart_path), type='png')
                                
                                if chart_path.exists():
                                    file_size = chart_path.stat().st_size
                                    logger.info(
                                        f"Chart screenshot saved: {filename}, size: {file_size} bytes",
                                        extra={
                                            "canvas_id": canvas_id,
                                            "canvas_index": canvas_index,
                                            "dimensions": f"{canvas_info['width']}x{canvas_info['height']}"
                                        }
                                    )
                                    print(f"[SCREENSHOT] Chart {canvas_index} ({canvas_id}) saved: {filename}, "
                                          f"size: {file_size} bytes, dimensions: {canvas_info['width']}x{canvas_info['height']}")
                                    chart_images.append(filename)
                                else:
                                    logger.warning(f"Chart screenshot file not created: {filename}")
                                    print(f"[SCREENSHOT] WARNING: Chart screenshot file not created: {filename}")
                            else:
                                logger.warning(f"Canvas element not found for index {canvas_index}")
                                print(f"[SCREENSHOT] WARNING: Canvas element not found for index {canvas_index}")
                        except Exception as e:
                            logger.warning(f"Failed to capture chart {canvas_index}: {e}", exc_info=True)
                            print(f"[SCREENSHOT] WARNING: Failed to capture chart {canvas_index}: {e}")
                else:
                    logger.info("No canvas elements found, no chart screenshots to capture")
                    print("[SCREENSHOT] No canvas elements found")
                
                await browser.close()
                return chart_images
                
        except Exception as e:
            logger.error("Screenshot failed", exc_info=True, extra={"html_path": html_path, "error": str(e)})
            print(f"[SCREENSHOT] ERROR: Screenshot failed: {e}")
            return []
    
    def _truncate_html(self, html_str: str, max_length: int = 15000) -> str:
        """Truncate HTML to reasonable length for LLM while preserving CSS.
        
        Args:
            html_str: HTML string to truncate
            max_length: Maximum length before truncation
        
        Returns:
            Truncated HTML string with CSS preserved
        """
        if len(html_str) <= max_length:
            logger.debug(
                "HTML within length limit, no truncation needed",
                extra={"html_length": len(html_str), "max_length": max_length}
            )
            return html_str
        
        logger.debug(
            "Truncating HTML for LLM (preserving CSS)",
            extra={
                "original_length": len(html_str),
                "max_length": max_length,
                "html_preview_before": html_str[:500] + "..." if len(html_str) > 500 else html_str,
            }
        )
        
        try:
            soup = BeautifulSoup(html_str, 'lxml')
            
            # CRITICAL: Preserve style tag with all CSS for color extraction
            # Extract style content before truncation
            style_tags = soup.find_all('style')
            style_content = '\n'.join([str(tag) for tag in style_tags])
            
            # Remove script tags (charts will use screenshots or extracted data)
            script_count = len(soup.find_all('script'))
            for script in soup.find_all('script'):
                script.decompose()
            
            # Get body content
            body_content = str(soup.body) if soup.body else ""
            
            # If still too long, truncate body but keep style
            if len(body_content) + len(style_content) > max_length:
                # Keep style tag, truncate body content
                body_max = max_length - len(style_content) - 500  # Reserve space for style
                if body_max > 0:
                    body_content = body_content[:body_max] + "..."
            
            # Reconstruct with style tag preserved
            truncated = f"<html><head>{style_content}</head>{body_content}</html>"
            
            logger.debug(
                "HTML truncated successfully (CSS preserved)",
                extra={
                    "original_length": len(html_str),
                    "truncated_length": len(truncated),
                    "style_length": len(style_content),
                    "scripts_removed": script_count,
                    "truncated_preview": truncated[:500] + "..." if len(truncated) > 500 else truncated,
                }
            )
            
            return truncated
        except Exception as e:
            logger.warning(
                "HTML truncation fallback to simple slice",
                exc_info=True,
                extra={
                    "error": str(e),
                    "original_length": len(html_str),
                }
            )
            # Even in fallback, try to preserve style tag
            if '<style>' in html_str and '</style>' in html_str:
                style_start = html_str.find('<style>')
                style_end = html_str.find('</style>') + 8
                style_tag = html_str[style_start:style_end]
                body_slice = html_str[style_end:style_end + (max_length - len(style_tag) - 100)]
                return f"<html><head>{style_tag}</head><body>{body_slice}...</body></html>"
            return html_str[:max_length]
    
    def _execute_single_slide_converter(
        self,
        code: str,
        html_str: str,
        output_path: str,
        assets_dir: str
    ) -> None:
        """Execute generated converter code for single slide.
        
        Args:
            code: Generated Python code
            html_str: HTML content
            output_path: Path to save PPTX
            assets_dir: Directory containing assets
        
        Raises:
            PPTXConversionError: If code execution fails
        """
        # Ensure required imports are present
        required_imports = """from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
import os
"""
        # Check if imports are already present
        if "from pptx import Presentation" not in code and "from pptx import" not in code:
            code = required_imports + "\n" + code
            logger.debug("Injected required imports into generated code")
        
        # Save code to temp file
        temp_module_path = Path(tempfile.mktemp(suffix=".py", prefix="converter_"))
        temp_module_path.write_text(code, encoding='utf-8')
        
        try:
            # Load as module
            spec = importlib.util.spec_from_file_location("temp_converter", str(temp_module_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Execute convert_to_pptx function
            module.convert_to_pptx(html_str, output_path, assets_dir)
            
        except Exception as e:
            logger.error("Failed to execute converter code", exc_info=True)
            raise PPTXConversionError(f"Code execution failed: {str(e)}") from e
        finally:
            # Cleanup temp module file
            if temp_module_path.exists():
                temp_module_path.unlink()
    
    def _execute_slide_adder(
        self,
        code: str,
        prs: Presentation,
        html_str: str,
        assets_dir: str
    ) -> None:
        """Execute generated code to add slide to presentation.
        
        Args:
            code: Generated Python code
            prs: Presentation object
            html_str: HTML content
            assets_dir: Directory containing assets
        """
        # Ensure required imports are present
        required_imports = """from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
import os
"""
        # Check if imports are already present
        if "from pptx.util import" not in code:
            code = required_imports + "\n" + code
            logger.debug("Injected required imports into generated code")
        
        # Save code to temp file
        temp_module_path = Path(tempfile.mktemp(suffix=".py", prefix="slide_adder_"))
        temp_module_path.write_text(code, encoding='utf-8')
        
        try:
            # Load as module
            spec = importlib.util.spec_from_file_location("temp_slide_adder", str(temp_module_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Execute add_slide_to_presentation function
            try:
                module.add_slide_to_presentation(prs, html_str, assets_dir)
            except Exception as e:
                logger.warning(
                    "Generated code error, creating fallback slide",
                    exc_info=True,
                    extra={"error": str(e)}
                )
                # Create a simple fallback slide with just a title
                slide = prs.slides.add_slide(prs.slide_layouts[6])
                from pptx.util import Inches, Pt
                from pptx.enum.text import PP_ALIGN
                from pptx.dml.color import RGBColor
                
                # Add a simple title
                title_box = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(8), Inches(1))
                title_frame = title_box.text_frame
                title_frame.text = "Slide Content"
                title_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
                title_frame.paragraphs[0].font.size = Pt(32)
                title_frame.paragraphs[0].font.color.rgb = RGBColor(16, 32, 37)
            
        finally:
            # Cleanup temp module file
            if temp_module_path.exists():
                temp_module_path.unlink()
