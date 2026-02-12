#!/usr/bin/env python3

import base64
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
        
        # 2. Chart screenshots are now captured client-side
        # Server-side Playwright capture has been removed
        chart_images = []
        if use_screenshot and html_source_path:
            logger.warning(
                "Server-side screenshot capture is no longer supported. "
                "Use client-side capture via chart_images parameter."
            )
            print("[PPTX_CONVERTER] WARNING: Server-side screenshots disabled. Use client-side capture.")
        
        # 2b. Extract base64 content images before sending to LLM
        html_str, content_images = self._extract_and_save_content_images(html_str, str(assets_dir))
        chart_images.extend(content_images)

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
        html_source_paths: Optional[List[str]] = None,
        chart_images_per_slide: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Convert multiple HTML slides to PowerPoint deck.
        
        Args:
            slides: List of HTML strings
            output_path: Path to save PPTX
            use_screenshot: Whether to capture screenshots
            html_source_paths: Paths to HTML files (for screenshots, if not using client images)
            chart_images_per_slide: List of dicts mapping canvas_id to base64 data URL per slide
        
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
            
            # Get chart images for this slide (if provided by client)
            slide_chart_images = None
            if chart_images_per_slide and i-1 < len(chart_images_per_slide):
                slide_chart_images = chart_images_per_slide[i-1]
                if slide_chart_images:
                    print(f"[PPTX_CONVERTER] Slide {i}: Received {len(slide_chart_images)} client chart images (IDs: {list(slide_chart_images.keys())})")
                else:
                    print(f"[PPTX_CONVERTER] Slide {i}: Received empty chart images dict")
            else:
                if chart_images_per_slide is None:
                    print(f"[PPTX_CONVERTER] Slide {i}: chart_images_per_slide is None")
                else:
                    print(f"[PPTX_CONVERTER] Slide {i}: No chart images at index {i-1} (total: {len(chart_images_per_slide)})")
            
            # Create slide and add content using V3 approach
            await self._add_slide_to_presentation(
                prs,
                html_str,
                use_screenshot=use_screenshot,
                html_source_path=html_path,
                slide_number=i,
                client_chart_images=slide_chart_images
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
        slide_number: int,
        client_chart_images: Optional[Dict[str, str]] = None
    ) -> None:
        """Add a slide to existing presentation using V3 approach.
        
        Args:
            prs: Presentation object to add slide to
            html_str: HTML content for the slide
            use_screenshot: Whether to capture and use screenshot
            html_source_path: Path to HTML file (for screenshot capture, if not using client images)
            slide_number: Slide number for logging purposes
            client_chart_images: Dict mapping canvas_id to base64 data URL (from client-side capture)
        """
        # 1. Setup working directory for this slide
        work_dir = Path(tempfile.mkdtemp(prefix=f"v3_slide_{slide_number}_"))
        assets_dir = work_dir / "assets"
        assets_dir.mkdir()
        
        # 2. Get chart images - prefer client-provided, fallback to server-side capture
        chart_images = []
        if use_screenshot:
            if client_chart_images:
                # Save client-provided base64 images to files
                logger.info(
                    "Saving client-provided chart images",
                    extra={
                        "slide_number": slide_number,
                        "chart_count": len(client_chart_images),
                        "assets_dir": str(assets_dir)
                    }
                )
                print(f"[PPTX_CONVERTER] Saving {len(client_chart_images)} client-provided chart images for slide {slide_number}")
                chart_images = self._save_client_chart_images(client_chart_images, str(assets_dir))
                if chart_images:
                    logger.info(
                        "Client chart images saved successfully",
                        extra={
                            "slide_number": slide_number,
                            "chart_count": len(chart_images),
                            "chart_files": chart_images
                        }
                    )
                    print(f"[PPTX_CONVERTER] Saved {len(chart_images)} chart images for slide {slide_number}: {chart_images}")
            elif html_source_path:
                # Server-side Playwright capture has been removed
                # Client-side capture should be used instead
                logger.warning(
                    "Server-side screenshot capture is no longer supported for slide",
                    extra={
                        "slide_number": slide_number,
                        "html_source_path": html_source_path
                    }
                )
                print(f"[PPTX_CONVERTER] WARNING: Server-side screenshots disabled for slide {slide_number}. Use client-side capture.")
            else:
                logger.warning("No chart screenshots captured", extra={"slide_number": slide_number})
                print(f"[PPTX_CONVERTER] WARNING: No chart screenshots captured for slide {slide_number}")
        
        # 2b. Extract base64 content images before sending to LLM
        html_str, content_images = self._extract_and_save_content_images(html_str, str(assets_dir))
        chart_images.extend(content_images)

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
            # Provide clear instructions with all available chart files
            if len(chart_images) == 1:
                screenshot_note = (
                    f"Chart image available: {chart_files_str}. "
                    f"CRITICAL: Use slide.shapes.add_picture(os.path.join(assets_dir, '{chart_images[0]}'), left, top, width, height) to add this image. "
                    f"Find the canvas element in the HTML (look for <canvas> tags) and position the image at that location. "
                    f"Typical position: left=1.0\", top=3.5\", width=8.0\", height=3.5\" (adjust based on HTML layout)."
                )
            else:
                screenshot_note = (
                    f"Chart images available: {chart_files_str}. "
                    f"CRITICAL: Use slide.shapes.add_picture() for each image. "
                    f"Match each image filename to its corresponding canvas element in the HTML by canvas ID or position. "
                    f"Find canvas elements in HTML and position images at their locations. "
                    f"Example: slide.shapes.add_picture(os.path.join(assets_dir, '{chart_images[0]}'), left, top, width, height)"
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
            # Provide clear instructions with all available chart files
            if len(chart_images) == 1:
                screenshot_note = (
                    f"Chart image available: {chart_files_str}. "
                    f"CRITICAL: Use slide.shapes.add_picture(os.path.join(assets_dir, '{chart_images[0]}'), left, top, width, height) to add this image. "
                    f"Find the canvas element in the HTML (look for <canvas> tags) and position the image at that location. "
                    f"Typical position: left=1.0\", top=3.5\", width=8.0\", height=3.5\" (adjust based on HTML layout)."
                )
            else:
                screenshot_note = (
                    f"Chart images available: {chart_files_str}. "
                    f"CRITICAL: Use slide.shapes.add_picture() for each image. "
                    f"Match each image filename to its corresponding canvas element in the HTML by canvas ID or position. "
                    f"Find canvas elements in HTML and position images at their locations. "
                    f"Example: slide.shapes.add_picture(os.path.join(assets_dir, '{chart_images[0]}'), left, top, width, height)"
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
                max_tokens=16384,
                extra_body={
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": 10240,
                    }
                },
            )
            
            code = self._extract_text_content(response.choices[0].message.content)
            
            logger.debug(
                "LLM response received",
                extra={
                    "code_length": len(code) if code else 0,
                    "code_preview": code[:500] + "..." if code and len(code) > 500 else code,
                }
            )
            
            # Extract code from markdown if wrapped
            code = self._strip_markdown_fences(code)
            
            return code
            
        except Exception as e:
            logger.error("LLM call failed", exc_info=True, extra={"error": str(e)})
            return None
    
    @staticmethod
    def _extract_text_content(content) -> str:
        """Extract text from LLM response, handling reasoning model responses.

        When reasoning/thinking is enabled, ``content`` is a list of blocks
        (e.g. [{"type": "reasoning", ...}, {"type": "text", "text": "..."}]).
        Otherwise it's a plain string.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
        # Fallback — stringify whatever we got
        return str(content) if content else ""

    @staticmethod
    def _strip_markdown_fences(code: str) -> str:
        """Remove markdown code fences from LLM-generated code.

        Handles variations like ```python, ```Python, ``` python, bare ```,
        trailing ```, and leading/trailing whitespace around fences.
        """
        # Try to extract content between ```python ... ``` (case-insensitive, optional whitespace)
        match = re.search(
            r"```[Pp]ython\s*\n(.*?)```", code, re.DOTALL
        )
        if match:
            return match.group(1).strip()

        # Try bare ``` ... ```
        match = re.search(r"```\s*\n(.*?)```", code, re.DOTALL)
        if match:
            return match.group(1).strip()

        # If the code just starts/ends with ``` on its own line, strip them
        lines = code.strip().splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    def _save_client_chart_images(
        self, 
        client_chart_images: Dict[str, str], 
        assets_dir: str
    ) -> list[str]:
        """Save client-provided base64 chart images to files.
        
        Args:
            client_chart_images: Dict mapping canvas_id to base64 data URL
            assets_dir: Directory to save chart images
        
        Returns:
            List of filenames of saved chart images (e.g., ['chart_0.png', 'chart_1.png'])
        """
        import base64
        
        chart_images = []
        assets_path = Path(assets_dir)
        
        for canvas_id, base64_data in client_chart_images.items():
            try:
                # Extract base64 data (remove data:image/png;base64, prefix if present)
                if ',' in base64_data:
                    base64_data = base64_data.split(',', 1)[1]
                
                # Decode base64 to bytes
                image_bytes = base64.b64decode(base64_data)
                
                # Determine filename from canvas_id
                # Canvas IDs might be like "chart_0", "my_chart", etc.
                if canvas_id.startswith('chart_'):
                    filename = f"{canvas_id}.png"
                else:
                    # Use canvas_id as filename, sanitize if needed
                    safe_id = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in canvas_id)
                    filename = f"chart_{safe_id}.png"
                
                chart_path = assets_path / filename
                chart_path.write_bytes(image_bytes)
                
                if chart_path.exists():
                    file_size = chart_path.stat().st_size
                    logger.info(
                        f"Saved client chart image: {filename}",
                        extra={
                            "canvas_id": canvas_id,
                            "filename": filename,
                            "file_size": file_size
                        }
                    )
                    print(f"[CLIENT_CHART] Saved chart image: {filename} ({file_size} bytes) from canvas_id: {canvas_id}")
                    chart_images.append(filename)
                else:
                    logger.warning(f"Chart image file not created: {filename}")
                    print(f"[CLIENT_CHART] WARNING: Chart image file not created: {filename}")
            except Exception as e:
                logger.warning(f"Failed to save client chart image {canvas_id}: {e}", exc_info=True)
                print(f"[CLIENT_CHART] WARNING: Failed to save chart image for canvas_id {canvas_id}: {e}")
        
        return chart_images
    
    # Regex matching <img> tags whose src is a base64 data URI.
    _BASE64_IMG_RE = re.compile(
        r'(<img\b[^>]*?\bsrc=")data:image/(png|jpeg|jpg|gif|svg\+xml);base64,([A-Za-z0-9+/=\s]+)(")',
        re.IGNORECASE,
    )

    # Map MIME sub-type to file extension
    _EXT_MAP = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "gif": ".gif", "svg+xml": ".svg"}

    def _extract_and_save_content_images(
        self, html_str: str, assets_dir: str
    ) -> tuple[str, list[str]]:
        """Extract base64-embedded images from HTML, save as files, replace src with filename.

        This prevents huge base64 blobs from being sent to the LLM (where they
        would be truncated by ``_truncate_html``).  The saved files are later
        merged into the ``chart_images`` list so the LLM receives
        ``add_picture()`` instructions for them.

        Args:
            html_str: HTML that may contain ``<img src="data:image/...;base64,...">`` tags.
            assets_dir: Directory to write extracted image files into.

        Returns:
            Tuple of (cleaned_html, list_of_saved_filenames).
        """
        filenames: list[str] = []
        counter = 0

        def _replace(match: re.Match) -> str:
            nonlocal counter
            prefix = match.group(1)       # '<img ... src="'
            mime_sub = match.group(2)      # 'png', 'jpeg', etc.
            b64_data = match.group(3)      # raw base64 payload
            suffix = match.group(4)        # closing '"'

            ext = self._EXT_MAP.get(mime_sub.lower(), ".png")
            filename = f"content_image_{counter}{ext}"
            counter += 1

            # Decode and write
            try:
                image_bytes = base64.b64decode(b64_data)
                filepath = Path(assets_dir) / filename
                filepath.write_bytes(image_bytes)
                filenames.append(filename)
                logger.info("Extracted content image", extra={"filename": filename, "size": len(image_bytes)})
            except Exception as e:
                logger.warning("Failed to extract content image", exc_info=True, extra={"error": str(e)})
                # Return original match unchanged on error
                return match.group(0)

            return f"{prefix}{filename}{suffix}"

        cleaned = self._BASE64_IMG_RE.sub(_replace, html_str)
        return cleaned, filenames

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
