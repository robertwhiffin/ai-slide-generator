#!/usr/bin/env python3
"""HTML to Google Slides converter using LLM code-gen approach."""

import base64
import importlib.util
import logging
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from databricks.sdk import WorkspaceClient

from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError
from src.services.google_slides_prompts_defaults import (
    DEFAULT_GSLIDES_SYSTEM_PROMPT,
    DEFAULT_GSLIDES_USER_PROMPT,
)

logger = logging.getLogger(__name__)


class GoogleSlidesConversionError(Exception):
    """Raised when Google Slides conversion fails."""


class HtmlToGoogleSlidesConverter:
    """LLM-powered converter: HTML → Google Slides API code → execution."""

    DEFAULT_MODEL = "databricks-claude-sonnet-4-5"

    def __init__(
        self,
        workspace_client: Optional[WorkspaceClient] = None,
        model_endpoint: Optional[str] = None,
        google_auth: Optional[GoogleSlidesAuth] = None,
    ):
        self.model_endpoint = model_endpoint or self.DEFAULT_MODEL

        if workspace_client:
            self.ws_client = workspace_client
        else:
            from src.core.databricks_client import get_databricks_client
            self.ws_client = get_databricks_client()

        self.llm_client = self.ws_client.serving_endpoints.get_open_ai_client()
        self.auth = google_auth or GoogleSlidesAuth()
        self.SYSTEM_PROMPT = DEFAULT_GSLIDES_SYSTEM_PROMPT
        self.USER_PROMPT = DEFAULT_GSLIDES_USER_PROMPT
        logger.info("Google Slides converter initialized", extra={"model": self.model_endpoint})

    # -- Public API --------------------------------------------------------

    async def convert_slide_deck(
        self,
        slides: List[str],
        title: str = "Presentation",
        chart_images_per_slide: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, str]:
        """Convert HTML slides to a Google Slides presentation."""
        total = len(slides)
        print(f"[GSLIDES_CONVERTER] Converting {total} slides to Google Slides "
              f"– total HTML size: {sum(len(h) for h in slides)}")

        try:
            slides_service = self.auth.build_slides_service()
            drive_service = self.auth.build_drive_service()
        except GoogleSlidesAuthError as exc:
            raise GoogleSlidesConversionError(f"Auth failed: {exc}") from exc

        try:
            pres = slides_service.presentations().create(body={"title": title}).execute()
            pres_id = pres["presentationId"]
            print(f"[GSLIDES_CONVERTER] Created presentation: {pres_id}")
        except Exception as exc:
            raise GoogleSlidesConversionError(f"Failed to create presentation: {exc}") from exc

        # Delete default blank slide
        default_slides = pres.get("slides", [])
        if default_slides:
            try:
                slides_service.presentations().batchUpdate(
                    presentationId=pres_id,
                    body={"requests": [{"deleteObject": {"objectId": default_slides[0]["objectId"]}}]},
                ).execute()
            except Exception:
                logger.warning("Failed to delete default slide", exc_info=True)

        # Process each slide
        for i, html_str in enumerate(slides, 1):
            print(f"[GSLIDES_CONVERTER] Processing slide {i}/{total} – HTML length: {len(html_str)}")
            page_id = f"slide_{uuid.uuid4().hex[:12]}"
            try:
                slides_service.presentations().batchUpdate(
                    presentationId=pres_id,
                    body={"requests": [{"createSlide": {
                        "objectId": page_id,
                        "insertionIndex": i - 1,
                        "slideLayoutReference": {"predefinedLayout": "BLANK"},
                    }}]},
                ).execute()
            except Exception:
                logger.error("Failed to create slide %d", i, exc_info=True)
                continue

            chart_imgs = None
            if chart_images_per_slide and i - 1 < len(chart_images_per_slide):
                chart_imgs = chart_images_per_slide[i - 1]

            await self._add_slide_content(
                slides_service, drive_service, pres_id, page_id,
                html_str, i, chart_imgs,
            )

        url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
        print(f"[GSLIDES_CONVERTER] Done: {url}")
        return {"presentation_id": pres_id, "presentation_url": url}

    # -- Per-slide pipeline ------------------------------------------------

    async def _add_slide_content(
        self, slides_service, drive_service, pres_id, page_id,
        html_str, slide_num, client_chart_images=None,
    ):
        """Generate code → execute → retry once on failure → fallback."""
        work_dir = Path(tempfile.mkdtemp(prefix=f"gslides_slide_{slide_num}_"))
        assets_dir = work_dir / "assets"
        assets_dir.mkdir()

        chart_images = []
        if client_chart_images:
            chart_images = self._save_chart_images(client_chart_images, str(assets_dir))
            if chart_images:
                print(f"[GSLIDES_CONVERTER] Slide {slide_num}: saved {len(chart_images)} chart images")

        code = await self._generate_code(html_str, chart_images)
        if not code:
            logger.warning("LLM returned no code for slide %d", slide_num)
            return

        error = self._execute_code(
            code, slides_service, drive_service, pres_id, page_id, html_str,
            str(assets_dir), slide_num,
        )
        if error is None:
            return

        # Retry with error context + original HTML so LLM doesn't hallucinate
        logger.info("Retrying slide %d with error context", slide_num)
        fixed = await self._retry_with_error(code, error, html_str, chart_images)
        if fixed:
            retry_err = self._execute_code(
                fixed, slides_service, drive_service, pres_id, page_id,
                html_str, str(assets_dir), slide_num,
            )
            if retry_err is None:
                return

        logger.warning("Slide %d: all attempts failed, adding fallback", slide_num)
        self._add_fallback(slides_service, pres_id, page_id, slide_num)

    # -- LLM calls ---------------------------------------------------------

    async def _generate_code(self, html_str, chart_images):
        """Generate Google Slides API code from HTML."""
        # Pass raw HTML — the LLM needs full CSS context for faithful styling.
        # Only truncate if excessively large.
        html_content = html_str if len(html_str) <= 25000 else html_str[:25000] + "\n<!-- truncated -->"
        screenshot_note = self._build_chart_note(chart_images)
        prompt = self.USER_PROMPT.format(
            html_content=html_content, screenshot_note=screenshot_note,
        )
        return await self._call_llm(self.SYSTEM_PROMPT, prompt)

    def _build_chart_note(self, chart_images):
        if not chart_images:
            return "No chart images available in assets_dir. If the HTML has <canvas> or Chart.js, skip the chart — do NOT try to recreate it with matplotlib or any other library."
        files = ", ".join(chart_images)
        return (
            f"CHART IMAGES in assets_dir: {files}\n"
            f"CRITICAL: You MUST use these pre-captured images. Do NOT recreate charts with matplotlib or any library.\n"
            f"Steps for each image:\n"
            f"  1. from googleapiclient.http import MediaFileUpload\n"
            f"  2. media = MediaFileUpload(os.path.join(assets_dir, filename), mimetype='image/png')\n"
            f"  3. Upload: file = drive_service.files().create(body={{'name': filename, 'mimeType': 'image/png'}}, media_body=media, fields='id').execute()\n"
            f"  4. Permission: drive_service.permissions().create(fileId=file['id'], body={{'type':'anyone','role':'reader'}}).execute()\n"
            f"  5. createImage with url=f'https://drive.google.com/uc?id={{file[\"id\"]}}'\n"
            f"Position: If chart is the main content, use left=0.4\", top=1.1\", width=9.0\", height=4.0\" (fills body zone).\n"
            f"If chart + metrics side-by-side, use left=0.4\", top=1.1\", width=4.5\", height=3.0\"."
        )

    async def _call_llm(self, system_prompt, user_prompt):
        """Call Databricks LLM and return code string."""
        try:
            resp = self.llm_client.chat.completions.create(
                model=self.model_endpoint,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=16384,
                extra_body={"thinking": {"type": "enabled", "budget_tokens": 10240}},
            )
            code = self._extract_text(resp.choices[0].message.content)
            return self._strip_fences(code) if code else None
        except Exception:
            logger.error("LLM call failed", exc_info=True)
            return None

    async def _retry_with_error(self, original_code, error_msg, html_str=None, chart_images=None):
        """Re-prompt LLM with error + original HTML context so it doesn't hallucinate."""
        html_content = ""
        if html_str:
            truncated = html_str if len(html_str) <= 15000 else html_str[:15000] + "\n<!-- truncated -->"
            html_content = f"\n\nOriginal HTML to convert:\n{truncated}\n"

        chart_note = ""
        if chart_images:
            chart_note = f"\n{self._build_chart_note(chart_images)}\n"

        fix_prompt = (
            f"Your previously generated code produced this error:\n\n"
            f"```\n{error_msg[:1500]}\n```\n\n"
            f"The failing code was:\n\n"
            f"```python\n{original_code[:4000]}\n```\n"
            f"{html_content}{chart_note}\n"
            f"Fix the error and return the complete corrected "
            f"add_slide_to_presentation function. Return ONLY Python code."
        )
        return await self._call_llm(self.SYSTEM_PROMPT, fix_prompt)

    @staticmethod
    def _extract_text(content):
        """Extract text from LLM response (handles reasoning model blocks)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
        return str(content) if content else ""

    @staticmethod
    def _strip_fences(code):
        """Remove markdown code fences."""
        m = re.search(r"```[Pp]ython\s*\n(.*?)```", code, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*\n(.*?)```", code, re.DOTALL)
        if m:
            return m.group(1).strip()
        lines = code.strip().splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    # -- Code sanitizer ----------------------------------------------------

    @staticmethod
    def _prepare_code(code):
        """Minimal prep: ensure function wrapper and fix smart quotes."""
        # Wrap bare code in function if LLM forgot the function definition
        if "def add_slide_to_presentation" not in code:
            logger.info("Prep: wrapping bare code in add_slide_to_presentation function")
            lines = code.split("\n")
            imports, body, helpers = [], [], []
            in_helper = False

            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")) and not body:
                    imports.append(line)
                elif stripped.startswith(("def emu(", "def hex_to_rgb(")):
                    in_helper = True
                    helpers.append(line)
                elif in_helper:
                    if stripped == "" or (line and line[0] == " "):
                        helpers.append(line)
                        if stripped == "":
                            in_helper = False
                    else:
                        in_helper = False
                        body.append(line)
                else:
                    body.append(line)

            indented = [("    " + l if l.strip() else "") for l in body]
            parts = []
            if imports:
                parts.append("\n".join(imports) + "\n")
            if helpers:
                parts.append("\n".join(helpers) + "\n")
            parts.append(
                "def add_slide_to_presentation(slides_service, drive_service, "
                "presentation_id, page_id, html_str, assets_dir):"
            )
            parts.extend(indented)
            code = "\n".join(parts)

        # Ensure imports
        if "import os" not in code:
            code = "import os\nimport json\nimport uuid\n\n" + code

        # Smart quotes → straight quotes (prevents SyntaxError)
        for smart, straight in {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}.items():
            code = code.replace(smart, straight)

        # Fix missing 'shapeProperties' wrapper in updateShapeProperties.
        # LLM consistently puts shapeBackgroundFill/outline directly inside
        # updateShapeProperties — the API requires them inside 'shapeProperties'.
        if ('updateShapeProperties' in code and 'shapeBackgroundFill' in code
                and 'shapeProperties' not in code):
            logger.info("Prep: injecting shapeProperties wrapper")
            lines = code.split('\n')
            out = []
            i = 0
            while i < len(lines):
                s = lines[i].strip()
                # Look for the shapeBackgroundFill line inside an updateShapeProperties block
                if ('shapeBackgroundFill' in s and s.startswith("'shapeBackgroundFill")
                        and i > 0 and 'objectId' in lines[i - 1]):
                    indent = len(lines[i]) - len(lines[i].lstrip())
                    out.append(' ' * indent + "'shapeProperties': {")
                    # Collect lines until we hit 'fields'
                    while i < len(lines):
                        fs = lines[i].strip()
                        if fs.startswith("'fields'") or fs.startswith('"fields"'):
                            out.append(' ' * indent + '},')
                            out.append(lines[i])
                            break
                        out.append(lines[i])
                        i += 1
                else:
                    out.append(lines[i])
                i += 1
            code = '\n'.join(out)

        return code

    # -- Code execution ----------------------------------------------------

    def _execute_code(self, code, slides_service, drive_service, pres_id, page_id,
                      html_str, assets_dir, slide_num):
        """Execute generated code. Returns None on success, error string on failure."""
        code = self._prepare_code(code)
        tmp = Path(tempfile.mktemp(suffix=".py", prefix="gslides_adder_"))
        tmp.write_text(code, encoding="utf-8")

        try:
            spec = importlib.util.spec_from_file_location("temp_gslides_adder", str(tmp))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.add_slide_to_presentation(
                slides_service, drive_service, pres_id, page_id, html_str, assets_dir,
            )
            return None
        except Exception as exc:
            debug_dir = Path("logs/gslides_debug")
            debug_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(tmp, debug_dir / f"slide_{slide_num}_{tmp.stem}.py")
            except Exception:
                pass
            logger.warning("Generated code failed for slide %d", slide_num, exc_info=True)
            return str(exc)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _add_fallback(self, slides_service, pres_id, page_id, slide_num):
        """Add a simple placeholder text box when all code-gen attempts fail."""
        eid = f"fallback_{uuid.uuid4().hex[:8]}"
        try:
            slides_service.presentations().batchUpdate(
                presentationId=pres_id,
                body={"requests": [
                    {"createShape": {
                        "objectId": eid, "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": page_id,
                            "size": {"width": {"magnitude": 7315200, "unit": "EMU"},
                                     "height": {"magnitude": 914400, "unit": "EMU"}},
                            "transform": {"scaleX": 1, "scaleY": 1,
                                          "translateX": 914400, "translateY": 2743200, "unit": "EMU"},
                        },
                    }},
                    {"insertText": {"objectId": eid, "text": f"Slide {slide_num}", "insertionIndex": 0}},
                    {"updateTextStyle": {
                        "objectId": eid,
                        "style": {"fontSize": {"magnitude": 32, "unit": "PT"},
                                  "foregroundColor": {"opaqueColor": {"rgbColor": {"red": 0.06, "green": 0.13, "blue": 0.15}}}},
                        "textRange": {"type": "ALL"}, "fields": "fontSize,foregroundColor",
                    }},
                    {"updateParagraphStyle": {
                        "objectId": eid, "style": {"alignment": "CENTER"},
                        "textRange": {"type": "ALL"}, "fields": "alignment",
                    }},
                ]},
            ).execute()
        except Exception:
            logger.error("Fallback content also failed", exc_info=True)

    # -- Chart image helpers -----------------------------------------------

    def _save_chart_images(self, chart_images_dict, assets_dir):
        """Save base64 chart images to files. Returns list of filenames."""
        saved = []
        assets = Path(assets_dir)
        for canvas_id, b64_data in chart_images_dict.items():
            try:
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                data = base64.b64decode(b64_data)
                name = f"{canvas_id}.png" if canvas_id.startswith("chart_") else \
                       f"chart_{''.join(c if c.isalnum() or c in '_-' else '_' for c in canvas_id)}.png"
                (assets / name).write_bytes(data)
                saved.append(name)
            except Exception as exc:
                logger.warning("Failed to save chart %s: %s", canvas_id, exc)
        return saved
