#!/usr/bin/env python
"""
Interactive multi-turn test for the SlideGeneratorAgent.

This script tests the multi-turn conversation capabilities with real connections:
- Real LLM calls to the configured endpoint
- Real Genie queries with conversation continuity
- Real MLflow tracing
- Interactive chat interface for follow-up questions

Usage:
    python test_multi_turn_live.py
    python test_multi_turn_live.py --question "Your initial question"
    python test_multi_turn_live.py --max-slides 5
    python test_multi_turn_live.py --auto  # Non-interactive mode
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


def print_colored(text: str, color: str = "default") -> None:
    """Print colored text."""
    colors = {
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "red": "\033[91m",
        "cyan": "\033[96m",
        "default": "\033[0m"
    }
    reset = "\033[0m"
    print(f"{colors.get(color, colors['default'])}{text}{reset}")


def check_databricks_credentials() -> None:
    """
    Check that Databricks credentials are configured.
    
    Raises:
        SystemExit: If credentials are not configured
    """
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    
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
        sys.exit(1)


def save_html_output(html: str, output_dir: Path = Path("output"), turn: int = 1) -> Path:
    """Save HTML output to a file."""
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"slides_turn{turn}_{timestamp}.html"
    output_file.write_text(html)
    return output_file


def display_turn_summary(turn: int, result: dict, elapsed: float, verbose: bool = False) -> None:
    """Display a summary of a conversation turn."""
    print_section(f"Turn {turn} - Results Summary")
    
    html = result.get("html", "")
    messages = result.get("messages", [])
    metadata = result.get("metadata", {})
    session_id = result.get("session_id", "")
    genie_conv_id = result.get("genie_conversation_id", "")
    
    print_result("Session ID", session_id[:12] + "..." if len(session_id) > 12 else session_id)
    if genie_conv_id:
        print_result("Genie Conversation ID", genie_conv_id[:12] + "..." if len(genie_conv_id) > 12 else genie_conv_id)
    print_result("HTML Length", f"{len(html):,} characters")
    print_result("New Messages", len(messages))
    print_result("Tool Calls", metadata.get("tool_calls", 0))
    print_result("Latency", f"{elapsed:.2f} seconds")
    print_result("Total Turns", metadata.get("message_count", turn))
    
    # Display conversation flow for this turn
    if verbose:
        print_section(f"Turn {turn} - Message Flow")
        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                print_colored(f"{i}. 👤 USER:", "cyan")
                print(f"   {content[:150]}...")
                
            elif role == "assistant":
                tool_call = msg.get("tool_call")
                if tool_call:
                    print_colored(f"{i}. 🤖 ASSISTANT (calling tool):", "blue")
                    print(f"   Tool: {tool_call.get('name')}")
                    args = tool_call.get('arguments', {})
                    query = args.get('query', '')
                    if query:
                        print(f"   Query: {query[:100]}...")
                else:
                    print_colored(f"{i}. 🤖 ASSISTANT (final response):", "green")
                    if content.startswith("<!DOCTYPE") or content.startswith("<html"):
                        print(f"   [HTML output - {len(content):,} chars]")
                    else:
                        preview = content[:200] if len(content) > 200 else content
                        print(f"   {preview}...")
                        
            elif role == "tool":
                print_colored(f"{i}. 🔧 TOOL RESPONSE:", "yellow")
                preview = content[:150] if len(content) > 150 else content
                print(f"   {preview}...")


def display_session_state(agent, session_id: str) -> None:
    """Display current session state."""
    try:
        session = agent.get_session(session_id)
        chat_history = session.get("chat_history")
        
        print_section("Session State")
        print_result("Session ID", session_id)
        print_result("Created At", session.get("created_at", "Unknown"))
        print_result("Message Count", session.get("message_count", 0))
        print_result("Last Interaction", session.get("last_interaction", "N/A"))
        print_result("Genie Conversation ID", session.get("genie_conversation_id") or "None yet")
        print_result("Chat History Messages", len(chat_history.messages))
        
        # Show conversation turns
        if chat_history.messages:
            print("\nConversation History:")
            for i, msg in enumerate(chat_history.messages, 1):
                role = "USER" if msg.__class__.__name__ == "HumanMessage" else "ASSISTANT"
                content = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
                if content.startswith("<!DOCTYPE") or content.startswith("<html"):
                    content = "[HTML Output]"
                print(f"  {i}. {role}: {content}")
    except AgentError as e:
        print_colored(f"⚠️  Could not retrieve session state: {e}", "red")


def interactive_loop(
    agent,
    session_id: str,
    max_slides: int = 5,
    verbose: bool = False,
    save_output: bool = True
) -> None:
    """
    Run interactive conversation loop.
    
    Args:
        agent: SlideGeneratorAgent instance
        session_id: Session ID for this conversation
        max_slides: Maximum slides per generation
        verbose: Show detailed output
        save_output: Save HTML files
    """
    turn = 1
    
    print_header("Interactive Multi-Turn Conversation")
    print_colored("💬 You can now ask follow-up questions!", "cyan")
    print_colored("   Type 'quit' or 'exit' to end the conversation", "yellow")
    print_colored("   Type 'state' to view session state", "yellow")
    print_colored("   Type 'help' for more commands", "yellow")
    
    while True:
        # Get user input
        print("\n" + "-" * 80)
        print_colored(f"Turn {turn + 1}:", "cyan")
        
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            break
        
        if not user_input:
            continue
        
        # Handle commands
        if user_input.lower() in ['quit', 'exit', 'q']:
            print_colored("\n👋 Ending conversation...", "yellow")
            break
        
        if user_input.lower() == 'state':
            display_session_state(agent, session_id)
            continue
        
        if user_input.lower() == 'help':
            print("\nAvailable commands:")
            print("  quit, exit, q  - End the conversation")
            print("  state          - View current session state")
            print("  help           - Show this help message")
            print("\nExample questions:")
            print("  - Add a slide comparing to last quarter")
            print("  - Change the color scheme to blue")
            print("  - Make the titles more concise")
            print("  - Add more data visualizations")
            continue
        
        # Generate slides with user's question
        print_colored(f"\n🤖 Generating response (this may take 30-60 seconds)...", "blue")
        
        start_time = datetime.now()
        try:
            result = agent.generate_slides(
                question=user_input,
                session_id=session_id,
                max_slides=max_slides
            )
            end_time = datetime.now()
            elapsed = (end_time - start_time).total_seconds()
            
            print_colored(f"✅ Response generated in {elapsed:.2f} seconds", "green")
            
            # Display results
            turn += 1
            display_turn_summary(turn, result, elapsed, verbose=verbose)
            
            # Save output
            if save_output:
                html = result.get("html", "")
                output_file = save_html_output(html, turn=turn)
                print_colored(f"\n💾 Saved to: {output_file}", "green")
            
        except AgentError as e:
            print_colored(f"❌ Error: {e}", "red")
            if verbose:
                import traceback
                traceback.print_exc()
            continue
        except Exception as e:
            print_colored(f"❌ Unexpected error: {e}", "red")
            if verbose:
                import traceback
                traceback.print_exc()
            break


def test_multi_turn_live(
    initial_question: str,
    max_slides: int = 5,
    verbose: bool = False,
    save_output: bool = True,
    interactive: bool = True
) -> dict:
    """
    Run a live multi-turn test with real LLM and Genie calls.
    
    Args:
        initial_question: Initial question to start conversation
        max_slides: Maximum number of slides to generate
        verbose: Print detailed output
        save_output: Save HTML to file
        interactive: Enable interactive mode for follow-ups
        
    Returns:
        Result dictionary from final turn
        
    Raises:
        AgentError: If agent execution fails
    """
    print_header("Multi-Turn Agent Test - Real LLM & Genie Integration")
    
    # Step 1: Create agent
    print_section("Step 1: Creating Agent")
    try:
        agent = create_agent()
        print_colored("✅ Agent created successfully", "green")
        print_result("LLM Endpoint", agent.settings.llm.endpoint)
        print_result("Genie Space ID", agent.settings.genie.space_id)
        print_result("MLflow Experiment", agent.settings.mlflow.experiment_name)
    except Exception as e:
        print_colored(f"❌ Failed to create agent: {e}", "red")
        raise
    
    # Step 2: Create session
    print_section("Step 2: Creating Conversation Session")
    try:
        session_id = agent.create_session()
        print_colored("✅ Session created successfully", "green")
        print_result("Session ID", session_id)
        print_result("Active Sessions", len(agent.list_sessions()))
    except Exception as e:
        print_colored(f"❌ Failed to create session: {e}", "red")
        raise
    
    # Step 3: Initial turn
    print_section(f"Step 3: Turn 1 - Initial Request (max {max_slides} slides)")
    print_colored(f"Question: {initial_question}", "cyan")
    print_colored("\n🤖 Generating slides (this may take 30-60 seconds)...", "blue")
    
    start_time = datetime.now()
    try:
        result = agent.generate_slides(
            question=initial_question,
            session_id=session_id,
            max_slides=max_slides
        )
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        print_colored(f"✅ Slides generated successfully in {elapsed:.2f} seconds", "green")
        
    except Exception as e:
        print_colored(f"❌ Failed to generate slides: {e}", "red")
        # Clean up session
        try:
            agent.clear_session(session_id)
        except:
            pass
        raise
    
    # Step 4: Display results
    display_turn_summary(1, result, elapsed, verbose=verbose)
    
    # Step 5: Save output
    if save_output:
        html = result.get("html", "")
        output_file = save_html_output(html, turn=1)
        print_colored(f"\n💾 Saved to: {output_file}", "green")
    
    # Step 6: Show session state
    display_session_state(agent, session_id)
    
    # Step 7: Interactive mode
    if interactive:
        interactive_loop(
            agent=agent,
            session_id=session_id,
            max_slides=max_slides,
            verbose=verbose,
            save_output=save_output
        )
    
    # Final cleanup
    print_section("Cleaning Up")
    try:
        session_data = agent.get_session(session_id)
        final_message_count = session_data.get("message_count", 1)
        agent.clear_session(session_id)
        print_colored("✅ Session cleaned up", "green")
        print_result("Total Turns", final_message_count)
    except Exception as e:
        print_colored(f"⚠️  Warning during cleanup: {e}", "yellow")
    
    # Final summary
    print_header("Multi-Turn Test Complete ✅")
    
    return result


def main():
    """Main entry point."""
    # Check credentials before parsing arguments
    check_databricks_credentials()
    
    parser = argparse.ArgumentParser(
        description="Test the SlideGeneratorAgent multi-turn conversation capabilities"
    )
    parser.add_argument(
        "--question",
        "-q",
        default="Create a brief overview of KPMG UK Consumption with 3-5 slides",
        help="Initial question to start the conversation"
    )
    parser.add_argument(
        "--max-slides",
        "-m",
        type=int,
        default=10,
        help="Maximum number of slides to generate (default: 10)"
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
    parser.add_argument(
        "--auto",
        "-a",
        action="store_true",
        help="Non-interactive mode (single turn only)"
    )
    
    args = parser.parse_args()
    
    try:
        result = test_multi_turn_live(
            initial_question=args.question,
            max_slides=args.max_slides,
            verbose=args.verbose,
            save_output=not args.no_save,
            interactive=not args.auto
        )
        
        # Exit with success
        sys.exit(0)
        
    except KeyboardInterrupt:
        print_colored("\n\n⚠️  Test interrupted by user", "yellow")
        sys.exit(1)
        
    except Exception as e:
        print_colored(f"\n\n❌ Test failed: {e}", "red")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

