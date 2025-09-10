#!/usr/bin/env python3
"""
Test 1: Send prompt to LLM and generate HTML output

This test replicates the exact flow of the gradio app:
1. Initialize HtmlDeck with EY theme 
2. Initialize Chatbot with LLM endpoint and UC tools
3. Send test prompt through conversation loop
4. Save HTML output to test/output/
"""

import base64
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))

from slide_generator.tools import html_slides, uc_tools
from slide_generator.core import chatbot
from slide_generator.config import config
from databricks.sdk import WorkspaceClient


def get_logo_base64():
    """Load the EY-Parthenon logo and encode it as base64 for embedding in HTML."""
    logo_path = Path(__file__).parent.parent / "src" / "slide_generator" / "assets" / "EY-Parthenon_Logo_2021.svg"
    try:
        with open(logo_path, 'rb') as logo_file:
            logo_data = logo_file.read()
            return base64.b64encode(logo_data).decode('utf-8')
    except FileNotFoundError:
        print(f"Warning: Logo file not found at {logo_path}")
        return ""


def test_llm_html_generation():
    """Test LLM HTML generation with the same setup as gradio app"""
    
    print("🚀 Starting Test 1: LLM HTML Generation")
    print(f"📊 Using LLM endpoint: {config.llm_endpoint}")
    
    # Initialize WorkspaceClient (same as gradio app)
    ws = WorkspaceClient(product='slide-generator')
    
    # Initialize EY theme (same as gradio app)
    ey_theme = html_slides.SlideTheme(
        bottom_right_logo_url="data:image/svg+xml;base64," + get_logo_base64(),
        bottom_right_logo_height_px=50,
        bottom_right_logo_margin_px=20
    )
    
    # Initialize HTML deck with theme
    html_deck = html_slides.HtmlDeck(theme=ey_theme)
    
    # Initialize chatbot (same as gradio app)
    chatbot_instance = chatbot.Chatbot(
        html_deck=html_deck,
        llm_endpoint_name=config.llm_endpoint,
        ws=ws,
        tool_dict=uc_tools.UC_tools
    )
    
    # Initialize conversation with system prompt (same as gradio app)
    openai_conversation = [{"role": "system", "content": config.system_prompt}]
    
    # Test prompt (provided by user)
    test_prompt = "Generate a succinct report EY Parthenon. Do not generate more than 5 slides. Use the information available in your tools. Use visualisations. Include an overview slide of EY Parthenon. Think about your response."
    
    print(f"📝 Test prompt: {test_prompt}")
    
    # Add user message to conversation
    user_msg = {"role": "user", "content": test_prompt}
    openai_conversation.append(user_msg)
    
    # Main conversation loop (same as gradio app handle_user_input)
    max_iterations = 30
    iteration = 0
    
    print("🔄 Starting conversation loop...")
    
    while iteration < max_iterations:
        iteration += 1
        print(f"  Iteration {iteration}/{max_iterations}")
        
        # Call LLM with OpenAI format conversation
        assistant_response, stop = chatbot_instance.call_llm(openai_conversation)
        print(f"  ✨ LLM Response: {assistant_response.get('content', 'Tool call')[:100]}...")
        
        # Add assistant response to conversation
        openai_conversation.append(assistant_response)
        
        # If assistant used tools, execute them
        if "tool_calls" in assistant_response:
            for tool_call in assistant_response["tool_calls"]:
                print(f"  🔧 Executing tool: {tool_call['function']['name']}")
                
                # Execute the tool
                try:
                    tool_result = chatbot_instance.execute_tool_call(tool_call)
                    if tool_result and "content" in tool_result:
                        content_preview = str(tool_result["content"])[:100]
                        print(f"  ✅ Tool result: {content_preview}...")
                        # Add tool result to conversation
                        openai_conversation.append(tool_result)
                    else:
                        print(f"  ⚠️ Tool returned None or invalid result: {tool_result}")
                        # Create a fallback tool result
                        fallback_result = {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": f"Tool {tool_call['function']['name']} executed but returned no content"
                        }
                        openai_conversation.append(fallback_result)
                except Exception as e:
                    print(f"  ❌ Tool execution failed: {e}")
                    # Create an error tool result
                    error_result = {
                        "role": "tool", 
                        "tool_call_id": tool_call["id"],
                        "content": f"Error executing {tool_call['function']['name']}: {str(e)}"
                    }
                    openai_conversation.append(error_result)
        
        # Check if we're done
        if stop:
            print("  🏁 Conversation complete (stop reason)")
            break
            
        # Safety check
        if iteration >= max_iterations:
            print("  ⚠️ Reached maximum iterations")
            break
    
    # Get final HTML output
    final_html = chatbot_instance.get_deck_html()
    
    # Save HTML to output directory
    output_path = Path(__file__).parent / "output" / "test_1_output.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_html)
    
    print(f"💾 HTML saved to: {output_path}")
    print(f"📏 HTML size: {len(final_html)} characters")
    
    # Verify output contains slides (reveal.js uses <section> tags)
    section_count = final_html.count("<section>")
    if section_count > 0:
        print(f"✅ Test 1 PASSED: HTML contains {section_count} slides")
        return True
    else:
        print("❌ Test 1 FAILED: HTML does not contain slides")
        return False


if __name__ == "__main__":
    success = test_llm_html_generation()
    sys.exit(0 if success else 1)