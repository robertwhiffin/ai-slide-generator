"""
Entry point for the slide generator package.

This allows running the package with:
    python -m slide_generator
"""

import sys
import argparse
from pathlib import Path

from .config import config
from .frontend.gradio_app import main as gradio_main


def main():
    """Main entry point for the slide generator CLI."""
    parser = argparse.ArgumentParser(
        description="AI-powered slide deck generator",
        prog="slide-generator"
    )
    
    parser.add_argument(
        "--mode", 
        choices=["gradio", "cli"], 
        default="gradio",
        help="Interface mode to use (default: gradio)"
    )
    
    parser.add_argument(
        "--host",
        default=config.gradio_host,
        help=f"Host for Gradio interface (default: {config.gradio_host})"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=config.gradio_port,
        help=f"Port for Gradio interface (default: {config.gradio_port})"
    )
    
    parser.add_argument(
        "--share",
        action="store_true",
        help="Share Gradio interface publicly"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=config.output_dir,
        help=f"Output directory for generated slides (default: {config.output_dir})"
    )
    
    args = parser.parse_args()
    
    # Update config with CLI arguments
    if args.debug:
        config.debug = True
        config.log_level = "DEBUG"
    
    if args.share:
        config.gradio_share = True
    
    config.gradio_host = args.host
    config.gradio_port = args.port
    config.output_dir = args.output_dir
    
    # Ensure output directory exists
    config.output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"🎨 Slide Generator v{getattr(__import__('slide_generator'), '__version__', '0.1.0')}")
    print(f"📁 Output directory: {config.output_dir}")
    print(f"🤖 LLM endpoint: {config.llm_endpoint}")
    
    if args.mode == "gradio":
        print("🚀 Starting Gradio interface...")
        gradio_main()
    elif args.mode == "cli":
        print("💻 CLI mode not yet implemented")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

