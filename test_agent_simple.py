#!/usr/bin/env python
"""
Simple live test for the SlideGeneratorAgent.

Quick test with minimal output. Good for rapid iteration.

Usage:
    python test_agent_simple.py
"""

import os
import sys

# Load .env file before anything else
from dotenv import load_dotenv
load_dotenv()

from src.services.agent import create_agent

def check_credentials():
    """Check Databricks credentials are set."""
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    
    if not host or not token:
        print("\n❌ ERROR: Databricks credentials not set!")
        print("\nSet environment variables:")
        print("  export DATABRICKS_HOST='https://your-workspace.cloud.databricks.com'")
        print("  export DATABRICKS_TOKEN='your-token'")
        sys.exit(1)

if __name__ == "__main__":
    check_credentials()
    
    print("🚀 Creating agent...")
    agent = create_agent()
    print(f"✅ Agent ready (endpoint: {agent.settings.llm.endpoint})")
    
    print("\n📊 Generating slides...")
    result = agent.generate_slides(
        question="I want a 5 slide consumption review of KPMG UK, starting from November 2024.",
        max_slides=5
    )
    
    print(f"✅ Done!")
    print(f"   - HTML: {len(result['html']):,} chars")
    print(f"   - Messages: {len(result['messages'])}")
    print(f"   - Tool calls: {result['metadata']['tool_calls']}")
    print(f"   - Time: {result['metadata']['latency_seconds']:.1f}s")
    
    # Save output
    from pathlib import Path
    from datetime import datetime
    
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"slides_{timestamp}.html"
    output_file.write_text(result['html'])
    
    print(f"\n📄 Saved: {output_file}")
    print(f"   Open with: open {output_file}")

