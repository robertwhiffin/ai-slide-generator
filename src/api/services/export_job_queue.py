"""In-memory job queue for async PPTX export processing.

This module provides a background worker that processes PPTX export requests
asynchronously, enabling polling-based export to work around
Databricks Apps' 60-second reverse proxy timeout.

Pattern mirrors job_queue.py for chat processing.
"""

import asyncio
import logging
import secrets
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory job tracking (job_id -> metadata)
export_jobs: Dict[str, Dict[str, Any]] = {}
export_queue: asyncio.Queue = asyncio.Queue()


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return secrets.token_urlsafe(24)


async def enqueue_export_job(job_id: str, payload: dict) -> None:
    """Add an export job to the queue.

    Args:
        job_id: Unique job identifier
        payload: Job payload with session_id, slides_html, chart_images, etc.
    """
    export_jobs[job_id] = {
        "status": "pending",
        "session_id": payload["session_id"],
        "progress": 0,
        "total_slides": payload.get("total_slides", 0),
        "queued_at": datetime.utcnow(),
        "output_path": None,
        "error": None,
    }
    await export_queue.put((job_id, payload))
    logger.info("Enqueued export job", extra={"job_id": job_id})


def get_export_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get export job status.

    Args:
        job_id: Job identifier

    Returns:
        Job metadata or None if not found
    """
    return export_jobs.get(job_id)


def update_export_progress(job_id: str, current: int, total: int) -> None:
    """Update export progress for a job.

    Args:
        job_id: Job identifier
        current: Current slide being processed (1-indexed)
        total: Total number of slides
    """
    if job_id in export_jobs:
        export_jobs[job_id]["progress"] = current
        export_jobs[job_id]["total_slides"] = total
        logger.debug(
            f"Export progress: {current}/{total}",
            extra={"job_id": job_id, "progress": current, "total": total},
        )


async def process_export_job(job_id: str, payload: dict) -> None:
    """Process a PPTX export job.

    This function:
    1. Updates job status to running
    2. Fetches slide deck and builds HTML for each slide
    3. Processes each slide with progress updates
    4. Stores the output file path
    5. Marks job as completed

    Args:
        job_id: Unique job identifier
        payload: Job payload with session_id, chart_images, etc.
    """
    from src.api.services.chat_service import get_chat_service
    from src.api.routes.export import build_slide_html
    from src.services.html_to_pptx import HtmlToPptxConverterV3, PPTXConversionError

    session_id = payload["session_id"]
    chart_images_per_slide: Optional[List[Dict[str, str]]] = payload.get(
        "chart_images_per_slide"
    )
    title: str = payload.get("title", "slides")

    try:
        # Fetch slide deck from database
        logger.info(f"Fetching slide deck for export job {job_id}")
        chat_service = get_chat_service()
        slide_deck = chat_service.get_slides(session_id)
        
        if not slide_deck or not slide_deck.get("slides"):
            raise ValueError("No slides available")
        
        slides = slide_deck.get("slides", [])
        total_slides = len(slides)
        export_jobs[job_id]["total_slides"] = total_slides
        
        # Build HTML for each slide (this is the slow part we moved here)
        logger.info(f"Building HTML for {total_slides} slides")
        slides_html: List[str] = []
        for i, slide in enumerate(slides):
            slide_html = build_slide_html(slide, slide_deck)
            slides_html.append(slide_html)
            logger.debug(f"Built HTML for slide {i+1}/{total_slides}")
        
    except Exception as e:
        logger.error(f"Failed to prepare slides for export: {e}", exc_info=True)
        export_jobs[job_id]["status"] = "error"
        export_jobs[job_id]["error"] = f"Failed to prepare slides: {str(e)}"
        return

    try:
        # Update status to running
        export_jobs[job_id]["status"] = "running"

        # Create temporary output file
        output_file = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pptx",
            prefix=f"export_{job_id}_",
        )
        output_path = output_file.name
        output_file.close()

        # Initialize converter
        converter = HtmlToPptxConverterV3()

        # Process slides with progress callback
        await convert_slides_with_progress(
            converter=converter,
            job_id=job_id,
            slides_html=slides_html,
            output_path=output_path,
            chart_images_per_slide=chart_images_per_slide,
        )

        # Store result
        export_jobs[job_id]["output_path"] = output_path
        export_jobs[job_id]["title"] = title
        export_jobs[job_id]["status"] = "completed"
        export_jobs[job_id]["completed_at"] = datetime.utcnow()

        logger.info(
            "Export job completed",
            extra={
                "job_id": job_id,
                "output_path": output_path,
                "total_slides": total_slides,
            },
        )

    except PPTXConversionError as e:
        logger.error(f"Export conversion failed: {e}", extra={"job_id": job_id})
        export_jobs[job_id]["status"] = "error"
        export_jobs[job_id]["error"] = f"Conversion failed: {str(e)}"

    except Exception as e:
        logger.error(f"Export job failed: {e}", extra={"job_id": job_id}, exc_info=True)
        export_jobs[job_id]["status"] = "error"
        export_jobs[job_id]["error"] = str(e)


async def convert_slides_with_progress(
    converter,
    job_id: str,
    slides_html: List[str],
    output_path: str,
    chart_images_per_slide: Optional[List[Dict[str, str]]] = None,
) -> None:
    """Convert slides to PPTX with progress updates.

    This wraps the converter to update progress after each slide.

    Args:
        converter: HtmlToPptxConverterV3 instance
        job_id: Job ID for progress updates
        slides_html: List of HTML strings for each slide
        output_path: Path to save PPTX
        chart_images_per_slide: Chart images per slide
    """
    from pptx import Presentation
    from pptx.util import Inches

    # Create presentation
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    total_slides = len(slides_html)

    # Process each slide
    for i, html_str in enumerate(slides_html, 1):
        update_export_progress(job_id, i, total_slides)

        # Get chart images for this slide
        slide_chart_images = None
        if chart_images_per_slide and i - 1 < len(chart_images_per_slide):
            slide_chart_images = chart_images_per_slide[i - 1]

        # Add slide to presentation
        await converter._add_slide_to_presentation(
            prs=prs,
            html_str=html_str,
            use_screenshot=True,
            html_source_path=None,
            slide_number=i,
            client_chart_images=slide_chart_images,
        )

        logger.debug(
            f"Processed slide {i}/{total_slides}",
            extra={"job_id": job_id, "slide": i, "total": total_slides},
        )

    # Save presentation
    prs.save(output_path)


async def export_worker() -> None:
    """Background worker that processes export jobs from the queue.
    
    Runs blocking export work in a thread pool to avoid blocking the event loop.
    This is critical - the LLM calls are synchronous and would otherwise block
    all async operations including HTTP response handling.
    """
    logger.info("Export job queue worker started")
    while True:
        try:
            job_id, payload = await export_queue.get()
            export_jobs[job_id]["status"] = "running"
            logger.info(f"Export worker picked up job {job_id}")

            try:
                # Run the blocking export work in a thread pool
                # This prevents LLM calls from blocking the event loop
                await asyncio.to_thread(_run_export_job_sync, job_id, payload)
            except Exception as e:
                export_jobs[job_id]["status"] = "error"
                export_jobs[job_id]["error"] = str(e)
                logger.error(
                    f"Export worker job failed: {e}", extra={"job_id": job_id}
                )

            export_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Export job queue worker shutting down")
            break
        except Exception as e:
            logger.error(f"Export worker loop error: {e}")


def _run_export_job_sync(job_id: str, payload: dict) -> None:
    """Synchronous wrapper to run export job in thread pool.
    
    This is called from asyncio.to_thread() to run blocking I/O
    (LLM calls, file operations) without blocking the event loop.
    """
    import asyncio
    
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(process_export_job(job_id, payload))
    finally:
        loop.close()


async def start_export_worker() -> asyncio.Task:
    """Start the background export worker task.

    Returns:
        The worker task handle
    """
    return asyncio.create_task(export_worker())


def cleanup_export_job(job_id: str) -> None:
    """Clean up job data and temporary files.

    Called after download or on error cleanup.

    Args:
        job_id: Job to clean up
    """
    job = export_jobs.pop(job_id, None)
    if job and job.get("output_path"):
        try:
            path = Path(job["output_path"])
            if path.exists():
                path.unlink()
                logger.debug(f"Cleaned up export file: {path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup export file: {e}")


def cleanup_stale_jobs(max_age_minutes: int = 30) -> int:
    """Clean up old completed/errored jobs.

    Args:
        max_age_minutes: Max age before cleanup

    Returns:
        Number of jobs cleaned up
    """
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    stale_jobs = [
        job_id
        for job_id, job in export_jobs.items()
        if job.get("status") in ("completed", "error")
        and job.get("queued_at", datetime.utcnow()) < cutoff
    ]

    for job_id in stale_jobs:
        cleanup_export_job(job_id)

    if stale_jobs:
        logger.info(f"Cleaned up {len(stale_jobs)} stale export jobs")

    return len(stale_jobs)
