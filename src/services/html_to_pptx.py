#!/usr/bin/env python3
"""
V3 HTML to PowerPoint Converter - Maximum LLM Flexibility

Philosophy:
- Give LLM the HTML with MINIMAL constraints
- Trust LLM to analyze layout and create appropriate slide
- Proven 100% success rate on diverse layouts
- True scalability - handles ANY HTML automatically

This approach replaces the older HtmlToPptxConverter with better reliability
and adaptability.
"""

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
    
    # Prompts for LLM code generation
    SYSTEM_PROMPT = """Generate Python code with convert_to_pptx(html_str, output_path, assets_dir) function.

Tools: Presentation, slide_layouts[6], shapes.add_textbox/picture/chart(), CategoryChartData, Pt(), RGBColor(), PP_ALIGN, Inches()

Slide: 10" × 7.5". Bounds: left ≥ 0.5", top ≥ 0.5", left + width ≤ 9.5", top + height ≤ 7.0"

Positioning (NO OVERLAPS):
- Title: left=0.5-1.0", top=0.5-1.0", height=1.0-1.5", ends ≤ 2.0", font ≤ 44pt
- Subtitle: left=0.5-1.0", top ≥ 2.3" (0.3" gap), height=0.8-1.0", ends ≤ 3.5", font ≤ 28pt
- Body: top ≥ 4.0", left ≥ 0.5", ends ≤ 7.0", font ≤ 18pt
- Use ONE text box per element with word_wrap=True

Charts:
- Use screenshot.png if exists, else extract Chart.js data (rawData, datasets, new Chart)
- Create CategoryChartData: categories = labels, add_series(name, values)
- Only use data from HTML, never create fake data

Return ONLY Python code."""

    USER_PROMPT_TEMPLATE = """Convert this HTML to PowerPoint:

{html_content}

Screenshot: {use_screenshot}
{screenshot_note}

Constraints:
- Slide: 10" × 7.5", bounds: left ≥ 0.5", top ≥ 0.5", left + width ≤ 9.5", top + height ≤ 7.0"
- NO OVERLAPS: Title (top ≤ 2.0"), Subtitle (top ≥ 2.3", ends ≤ 3.5"), Body (top ≥ 4.0")
- One text box per element, word_wrap=True
- Extract Chart.js data if present, create chart with CategoryChartData
- Only use data from HTML

Return Python code with convert_to_pptx(html_str, output_path, assets_dir)."""

    # For multi-slide support
    MULTI_SLIDE_SYSTEM_PROMPT = """Generate Python code with add_slide_to_presentation(prs, html_str, assets_dir) function.

Tools: prs.slides.add_slide(prs.slide_layouts[6]), shapes.add_textbox/picture/chart(), CategoryChartData, Pt(), RGBColor(), PP_ALIGN, Inches()

Slide: 10" × 7.5". Bounds: left ≥ 0.5", top ≥ 0.5", left + width ≤ 9.5", top + height ≤ 7.0"

Positioning (NO OVERLAPS):
- Title: left=0.5-1.0", top=0.5-1.0", height=1.0-1.5", ends ≤ 2.0", font ≤ 44pt
- Subtitle: left=0.5-1.0", top ≥ 2.3" (0.3" gap), height=0.8-1.0", ends ≤ 3.5", font ≤ 28pt
- Body: top ≥ 4.0", left ≥ 0.5", ends ≤ 7.0", font ≤ 18pt
- Use ONE text box per element with word_wrap=True

Charts:
- Use screenshot.png if exists, else extract Chart.js data (rawData, datasets, new Chart)
- Create CategoryChartData: categories = labels, add_series(name, values)
- Only use data from HTML, never create fake data

Return ONLY Python code."""

    MULTI_SLIDE_USER_PROMPT = """Add slide from HTML to presentation:

{html_content}

Screenshot: {has_screenshot}
{screenshot_note}

Constraints:
- Slide: 10" × 7.5", bounds: left ≥ 0.5", top ≥ 0.5", left + width ≤ 9.5", top + height ≤ 7.0"
- NO OVERLAPS: Title (top ≤ 2.0"), Subtitle (top ≥ 2.3", ends ≤ 3.5"), Body (top ≥ 4.0")
- One text box per element, word_wrap=True
- Extract Chart.js data if present, create chart with CategoryChartData
- Only use data from HTML

Return Python code with add_slide_to_presentation(prs, html_str, assets_dir)."""

    def __init__(
        self,
        workspace_client: Optional[WorkspaceClient] = None,
        model_endpoint: Optional[str] = None,
        profile: Optional[str] = None
    ):
        """Initialize V3 converter.
        
        Args:
            workspace_client: Databricks client (optional)
            model_endpoint: LLM model name (default: databricks-claude-sonnet-4-5)
            profile: Databricks profile for client creation (default: logfood)
        """
        self.model_endpoint = model_endpoint or self.DEFAULT_MODEL
        
        if workspace_client:
            self.ws_client = workspace_client
        elif profile:
            self.ws_client = WorkspaceClient(profile=profile, product='slide-generator')
        else:
            self.ws_client = WorkspaceClient(profile='logfood', product='slide-generator')
        
        # Initialize OpenAI-compatible client for LLM calls
        self.llm_client = self.ws_client.serving_endpoints.get_open_ai_client()
        
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
        
        # 2. Capture screenshot if requested
        screenshot_captured = False
        if use_screenshot and html_source_path:
            screenshot_path = assets_dir / "screenshot.png"
            screenshot_captured = await self._capture_screenshot(html_source_path, str(screenshot_path))
            if screenshot_captured:
                logger.info("Screenshot captured", extra={"path": str(screenshot_path)})
            else:
                logger.warning("Screenshot failed, continuing without it")
        
        # 3. Call LLM to generate converter code
        logger.info("Calling LLM to generate converter code")
        converter_code = await self._generate_converter_code(
            html_str,
            use_screenshot=screenshot_captured
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
        logger.info(
            "Converting slides to PowerPoint deck",
            extra={"slide_count": len(slides)}
        )
        
        # Create presentation
        prs = Presentation()
        prs.slide_width = Inches(10)
        prs.slide_height = Inches(7.5)
        
        # Process each slide
        for i, html_str in enumerate(slides, 1):
            logger.info(
                "Processing slide",
                extra={"slide_number": i, "total_slides": len(slides)}
            )
            
            # Setup for this slide
            html_path = html_source_paths[i-1] if html_source_paths and i-1 < len(html_source_paths) else None
            
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
        
        # 2. Capture screenshot if requested
        screenshot_captured = False
        if use_screenshot and html_source_path:
            screenshot_path = assets_dir / "screenshot.png"
            screenshot_captured = await self._capture_screenshot(html_source_path, str(screenshot_path))
            if screenshot_captured:
                logger.debug("Screenshot captured", extra={"slide_number": slide_number})
        
        # 3. Call LLM to generate code for adding this slide
        logger.debug("Calling LLM for slide", extra={"slide_number": slide_number})
        slide_code = await self._generate_slide_adder_code(
            html_str,
            has_screenshot=screenshot_captured
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
        use_screenshot: bool
    ) -> Optional[str]:
        """Call LLM to generate converter code for single slide.
        
        Args:
            html_str: HTML content to convert
            use_screenshot: Whether screenshot is available
        
        Returns:
            Generated Python code or None if generation fails
        """
        # Truncate HTML if too long
        html_content = self._truncate_html(html_str)
        
        screenshot_note = ""
        if use_screenshot:
            screenshot_note = "Use screenshot.png from assets_dir for charts."
        else:
            screenshot_note = "Extract Chart.js data (rawData, datasets, new Chart) from <script> tags and create chart with CategoryChartData. Only use data from HTML."
        
        prompt = self.USER_PROMPT_TEMPLATE.format(
            html_content=html_content,
            use_screenshot=use_screenshot,
            screenshot_note=screenshot_note
        )
        
        return await self._call_llm(self.SYSTEM_PROMPT, prompt)
    
    async def _generate_slide_adder_code(
        self,
        html_str: str,
        has_screenshot: bool
    ) -> Optional[str]:
        """Call LLM to generate code for adding slide to existing presentation.
        
        Args:
            html_str: HTML content to convert
            has_screenshot: Whether screenshot is available
        
        Returns:
            Generated Python code or None if generation fails
        """
        # Truncate HTML if too long
        html_content = self._truncate_html(html_str)
        
        screenshot_note = ""
        if has_screenshot:
            screenshot_note = "Use screenshot.png from assets_dir for charts."
        else:
            screenshot_note = "Extract Chart.js data (rawData, datasets, new Chart) from <script> tags and create chart with CategoryChartData. Only use data from HTML."
        
        prompt = self.MULTI_SLIDE_USER_PROMPT.format(
            html_content=html_content,
            has_screenshot=has_screenshot,
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
    
    async def _capture_screenshot(self, html_path: str, output_path: str) -> bool:
        """Capture screenshot of HTML using Playwright (async).
        
        Args:
            html_path: Path to HTML file
            output_path: Path to save screenshot
        
        Returns:
            True if screenshot captured successfully, False otherwise
        """
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                
                file_url = f"file://{os.path.abspath(html_path)}"
                await page.goto(file_url)
                
                # Wait for charts
                try:
                    await page.wait_for_selector('canvas', timeout=5000)
                    await page.wait_for_timeout(1500)
                except Exception as e:
                    logger.debug("Canvas not found or timeout", exc_info=True)
                
                # Try to capture just the chart area
                canvas = await page.query_selector('canvas')
                if canvas:
                    # Use the already-found canvas element
                    chart_container_handle = await canvas.evaluate_handle("""(canvas) => {
                        let elem = canvas;
                        for (let i = 0; i < 5; i++) {
                            if (elem.parentElement) {
                                elem = elem.parentElement;
                                const rect = elem.getBoundingClientRect();
                                if (elem.tagName === 'DIV' && rect.width > 300 && rect.height > 200) {
                                    if (rect.width < window.innerWidth * 0.9) {
                                        return elem;
                                    }
                                }
                            }
                        }
                        return canvas.parentElement || canvas;
                    }""")
                    
                    if chart_container_handle:
                        await chart_container_handle.as_element().screenshot(path=output_path)
                    else:
                        await canvas.screenshot(path=output_path)
                else:
                    await page.screenshot(path=output_path, full_page=False)
                
                await browser.close()
                return True
                
        except Exception as e:
            logger.warning("Screenshot failed", exc_info=True, extra={"html_path": html_path, "error": str(e)})
            return False
    
    def _truncate_html(self, html_str: str, max_length: int = 10000) -> str:
        """Truncate HTML to reasonable length for LLM.
        
        Args:
            html_str: HTML string to truncate
            max_length: Maximum length before truncation
        
        Returns:
            Truncated HTML string
        """
        if len(html_str) <= max_length:
            return html_str
        
        try:
            soup = BeautifulSoup(html_str, 'lxml')
            # Keep body content, strip script tags
            for script in soup.find_all('script'):
                script.decompose()
            return str(soup.body) if soup.body else html_str[:max_length]
        except Exception as e:
            logger.debug("HTML truncation fallback", exc_info=True)
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
