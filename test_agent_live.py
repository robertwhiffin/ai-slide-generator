#!/usr/bin/env python
"""
Live end-to-end test for the SlideGeneratorAgent.

This script tests the agent with real Databricks connections (no mocks):
- Real LLM calls to the configured endpoint
- Real Genie queries to the configured space (with automatic conversation management)
- Real MLflow tracing
- Session-based conversation state

Usage:
    python test_agent_live.py
    python test_agent_live.py --question "Your custom question"
    python test_agent_live.py --max-slides 5
    python test_agent_live.py --verbose
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Load .env file before anything else
from dotenv import load_dotenv
load_dotenv()

from src.services.agent import create_agent, AgentError


def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def print_section(text: str) -> None:
    """Print a formatted section header."""
    print(f"\n--- {text} ---\n")


def print_result(key: str, value: any) -> None:
    """Print a key-value result."""
    print(f"  {key}: {value}")


def check_databricks_credentials() -> None:
    """
    Check that Databricks credentials are configured.
    
    MLflow requires DATABRICKS_HOST and DATABRICKS_TOKEN for authentication.
    
    Raises:
        SystemExit: If credentials are not configured
    """
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    
    # Also check for profile in config
    try:
        from src.config.settings import get_settings
        settings = get_settings()
        profile = settings.databricks_profile
    except Exception:
        profile = None
    
    if not host and not token and not profile:
        print("\n❌ ERROR: Databricks credentials not configured!")
        print("\nMLflow requires authentication. Please set one of:")
        print("\n1. Environment variables (recommended for this test):")
        print("   export DATABRICKS_HOST='https://your-workspace.cloud.databricks.com'")
        print("   export DATABRICKS_TOKEN='your-token'")
        print("\n2. Profile in config/config.yaml:")
        print("   databricks:")
        print("     profile: 'your-profile-name'")
        print("\nCurrent status:")
        print(f"  DATABRICKS_HOST: {'✅ Set' if host else '❌ Not set'}")
        print(f"  DATABRICKS_TOKEN: {'✅ Set' if token else '❌ Not set'}")
        print(f"  Config profile: {'✅ ' + profile if profile else '❌ Not set'}")
        sys.exit(1)
    
    # Verify format if host is set
    if host and not host.startswith(("https://", "http://")):
        print("\n⚠️  WARNING: DATABRICKS_HOST should start with https://")
        print(f"   Current value: {host}")
        print(f"   Expected format: https://your-workspace.cloud.databricks.com")


def save_html_output(html: str, output_dir: Path = Path("output")) -> Path:
    """Save HTML output to a file."""
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"slides_{timestamp}.html"
    output_file.write_text(html)
    return output_file


def test_agent_live(
    question: str,
    max_slides: int = 5,
    verbose: bool = False,
    save_output: bool = True
) -> dict:
    """
    Run a live test of the agent with real LLM and Genie calls.
    
    This test demonstrates the new session-based approach where Genie
    conversation IDs are managed automatically, eliminating LLM hallucination risk.
    
    Args:
        question: Question to ask the agent
        max_slides: Maximum number of slides to generate
        verbose: Print detailed output
        save_output: Save HTML to file
        
    Returns:
        Result dictionary from agent including session_id and genie_conversation_id
        
    Raises:
        AgentError: If agent execution fails
    """
    print_header("Live Agent Test - Real LLM & Genie Integration")
    
    # Step 1: Create agent
    print_section("Step 1: Creating Agent")
    try:
        agent = create_agent()
        print("✅ Agent created successfully")
        print_result("LLM Endpoint", agent.settings.llm.endpoint)
        print_result("Genie Space ID", agent.settings.genie.space_id)
        print_result("MLflow Experiment", agent.settings.mlflow.experiment_name)
        print_result("MLflow Experiment ID", agent.experiment_id)
    except Exception as e:
        print(f"❌ Failed to create agent: {e}")
        raise
    
    # Step 2: Create session (initializes Genie conversation)
    print_section("Step 2: Creating Session")
    print("Initializing Genie conversation...")
    try:
        session_id = agent.create_session()
        print("✅ Session created successfully")
        print_result("Session ID", session_id)
        
        # Get session to show Genie conversation ID
        session = agent.get_session(session_id)
        print_result("Genie Conversation ID", session["genie_conversation_id"])
    except Exception as e:
        print(f"❌ Failed to create session: {e}")
        raise
    
    # Step 3: Generate slides
    print_section(f"Step 3: Generating Slides (max {max_slides})")
    print(f"Question: {question}")
    print("\nCalling LLM and Genie (this may take 30-60 seconds)...")
    
    start_time = datetime.now()
    try:
        result = agent.generate_slides(
            question=question,
            session_id=session_id,
            session_id=session_id,
            max_slides=max_slides
        )
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        print(f"✅ Slides generated successfully in {elapsed:.2f} seconds")
        
    except Exception as e:
        print(f"❌ Failed to generate slides: {e}")
        raise
    
    # Step 4: Analyze results
    print_section("Step 4: Results Summary")
    # Step 4: Analyze results
    print_section("Step 4: Results Summary")
    
    html = result.get("html", "")
    messages = result.get("messages", [])
    metadata = result.get("metadata", {})
    session_id = result.get("session_id", "unknown")
    genie_conversation_id = result.get("genie_conversation_id", "unknown")
    
    print_result("Session ID", session_id)
    print_result("Genie Conversation ID", genie_conversation_id)
    print_result("HTML Length", f"{len(html):,} characters")
    print_result("Total Messages", len(messages))
    print_result("Tool Calls", metadata.get("tool_calls", 0))
    print_result("Latency", f"{metadata.get('latency_seconds', 0):.2f} seconds")
    
    # Step 5: Show message flow
    print_section("Step 5: Conversation Flow")
    # Step 5: Show message flow
    print_section("Step 5: Conversation Flow")
    
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        
        if role == "user":
            print(f"{i}. 👤 USER:")
            print(f"   {content[:100]}...")
            
        elif role == "assistant":
            tool_call = msg.get("tool_call")
            if tool_call:
                print(f"{i}. 🤖 ASSISTANT (calling tool):")
                print(f"   Tool: {tool_call.get('name')}")
                if verbose:
                    args = tool_call.get('arguments', {})
                    print(f"   Arguments: {json.dumps(args, indent=2)}")
            else:
                print(f"{i}. 🤖 ASSISTANT (final response):")
                preview = content[:200] if len(content) > 200 else content
                if content.startswith("<!DOCTYPE") or content.startswith("<html"):
                    print(f"   [HTML output - {len(content)} chars]")
                else:
                    print(f"   {preview}...")
                    
        elif role == "tool":
            print(f"{i}. 🔧 TOOL RESPONSE:")
            preview = content[:150] if len(content) > 150 else content
            print(f"   {preview}...")
            if verbose:
                print(f"\n   Full response:\n{content}\n")
    
    # Step 6: HTML preview
    print_section("Step 6: HTML Preview")
    # Step 6: HTML preview
    print_section("Step 6: HTML Preview")
    
    if html.startswith("<!DOCTYPE") or html.startswith("<html"):
        print("✅ Valid HTML detected")
        
        # Count some HTML elements
        slide_divs = html.count("<div class=\"slide")
        h1_tags = html.count("<h1>")
        h2_tags = html.count("<h2>")
        tables = html.count("<table")
        
        print_result("Slide divs found", slide_divs)
        print_result("H1 headers", h1_tags)
        print_result("H2 headers", h2_tags)
        print_result("Tables", tables)
        
        # Show first 500 chars
        if verbose:
            print("\nFirst 500 characters of HTML:")
            print("-" * 80)
            print(html[:500])
            print("-" * 80)
    else:
        print("⚠️  Output doesn't appear to be HTML")
        print("First 200 chars:")
        print(html[:200])
    
    # Step 7: Save output
    # Step 7: Save output
    if save_output:
        print_section("Step 7: Saving Output")
        print_section("Step 7: Saving Output")
        try:
            output_file = save_html_output(html)
            print(f"✅ HTML saved to: {output_file}")
            print(f"\nOpen in browser:")
            print(f"   open {output_file}")
        except Exception as e:
            print(f"⚠️  Failed to save HTML: {e}")
    
    # Final summary
    print_header("Test Complete ✅")
    print(f"Total execution time: {elapsed:.2f} seconds")
    print(f"Tool calls made: {metadata.get('tool_calls', 0)}")
    print(f"Messages exchanged: {len(messages)}")
    
    if save_output:
        print(f"\n📄 View your slides: open {output_file}")
    
    return result


def main():
    """Main entry point."""
    # Check credentials before parsing arguments
    check_databricks_credentials()
    
    parser = argparse.ArgumentParser(
        description="Test the SlideGeneratorAgent with real LLM and Genie calls"
    )
    parser.add_argument(
        "--question",
        "-q",
        default=""""create a 5 slide report about KPMG UK's databricks usage, historic and forward looking"
        """,
        help="Question to ask the agent"
    )
    parser.add_argument(
        "--max-slides",
        "-m",
        type=int,
        default=50,
        help="Maximum number of slides to generate (default: 5)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose output including full tool responses"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save HTML output to file"
    )
    
    args = parser.parse_args()
    
    try:
        result = test_agent_live(
            question=args.question,
            max_slides=args.max_slides,
            verbose=args.verbose,
            save_output=not args.no_save
        )
        
        # Exit with success
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n\n❌ Test failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

