import html
import gradio as gr
from pathlib import Path
from slide_generator.tools import html_slides
from slide_generator.core import chatbot
from slide_generator.config import config, get_output_path
from databricks.sdk import WorkspaceClient

ws = WorkspaceClient(product='slide-generator')

# Initialize chatbot and conversation state
html_deck = html_slides.HtmlDeck()
chatbot_instance = chatbot.Chatbot(html_deck=html_deck, llm_endpoint_name=config.llm_endpoint, ws=ws)

# Dual conversation lists - OpenAI format for LLM, Gradio format for display
openai_conversation = [{"role": "system", "content": config.system_prompt}]
gradio_conversation = []  # Don't include system message in Gradio display


def openai_to_gradio_message(openai_msg):
    """Convert OpenAI format message to Gradio ChatMessage"""
    if openai_msg["role"] == "system":
        return None  # Don't display system messages in Gradio
    
    elif openai_msg["role"] == "user":
        return gr.ChatMessage(role="user", content=openai_msg["content"])
    
    elif openai_msg["role"] == "assistant":
        if "tool_calls" in openai_msg:
            # Assistant with tool calls
            content = openai_msg["content"] if openai_msg["content"] else "Using a tool"
            return gr.ChatMessage(
                role="assistant",
                content=content,
                metadata={"title": "🔧 Using a tool"}
            )
        else:
            # Regular assistant message
            return gr.ChatMessage(role="assistant", content=openai_msg["content"])
    
    elif openai_msg["role"] == "tool":
        # Tool result - display as assistant message with special formatting
        return gr.ChatMessage(
            role="assistant", 
            content=f"✅ {openai_msg['content']}",
            metadata={"title": "🔧 Tool result"}
        )
    
    return None


def gradio_to_openai_message(gradio_msg):
    """Convert Gradio ChatMessage to OpenAI format"""
    return {
        "role": gradio_msg.role,
        "content": gradio_msg.content
    }


def update_conversations_with_openai_message(openai_msg):
    """Add OpenAI message to both conversation lists"""
    openai_conversation.append(openai_msg)
    gradio_msg = openai_to_gradio_message(openai_msg)
    if gradio_msg is not None:
        gradio_conversation.append(gradio_msg)



def handle_user_input(user_input):
    """Handle user input with the stateless chatbot workflow"""
    if not user_input.strip():
        yield gradio_conversation, ""
    
    # Add user message to both conversations
    user_msg_openai = {"role": "user", "content": user_input}
    update_conversations_with_openai_message(user_msg_openai)
    yield gradio_conversation, ""
    
    # Main conversation loop until finish_reason == "stop"
    max_iterations = 10
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # Call LLM with OpenAI format conversation
        assistant_response, stop = chatbot_instance.call_llm(openai_conversation)
        
        # Add assistant response to conversations
        update_conversations_with_openai_message(assistant_response)
        yield gradio_conversation, ""
        
        # If assistant used tools, execute them
        if "tool_calls" in assistant_response:
            for tool_call in assistant_response["tool_calls"]:
                # Execute the tool
                tool_result = chatbot_instance.execute_tool_call(tool_call)
                
                # Add tool result to conversations
                update_conversations_with_openai_message(tool_result)
                yield gradio_conversation, ""
        
        # Check if we're done
        if stop:
            break
            
        # Safety check
        if iteration >= max_iterations:
            error_msg = {"role": "assistant", "content": "Reached maximum iterations. Please try a simpler request."}
            update_conversations_with_openai_message(error_msg)
            break
    # Return updated Gradio conversation and clear input
    yield gradio_conversation, ""



def update_slides():
    """Update slides display with current deck HTML"""
    current_html = chatbot_instance.get_deck_html()
    
    iframe = (
        '<div style="position:relative;width:100%;max-width:100%;aspect-ratio:16/9;">'
        f'  <iframe srcdoc="{html.escape(current_html)}" '
        '          style="position:absolute;inset:0;width:100%;height:100%;border:none;"></iframe>'
        '</div>'
    )
    return iframe


with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("""# 🎨 EY Slide Generator Demo""")
    gr.Markdown("Create professional slide decks using natural language with AI assistance")
    
    with gr.Row():
        with gr.Column():
            gr.Markdown("## 💬 Slide Creation Assistant")
            chatbox = gr.Chatbot(
                value=gradio_conversation,
                type="messages",
                placeholder="Start by asking me to create slides! For example: 'Create a 3-slide deck about AI benefits'",
                height=500
            )
            input_box = gr.Textbox(
                placeholder="Enter your slide creation request here...",
                lines=2,
                max_lines=5
            )
            input_box.submit(fn=handle_user_input, inputs=input_box, outputs=[chatbox, input_box])

        with gr.Column():
            gr.Markdown("## 🎯 Generated Slides")
            slides_display = gr.HTML(value=update_slides())
            update_button = gr.Button("🔄 Refresh Slides", variant="secondary")
            update_button.click(fn=update_slides, inputs=None, outputs=slides_display)
            chatbox.change(fn=update_slides, outputs=slides_display)
            
            gr.Markdown("### 💡 Tips:")
            gr.Markdown("""
            - Ask for specific slide types: title, agenda, content slides
            - Specify the number of slides you want
            - Request specific topics or themes
            - Use natural language - I'll understand what you need!
            """)
    gr.Markdown("Debugging")
    with gr.Row():
        with gr.Column():
            gr.Markdown("OpenAI Conversation")
            openai_conversation_display = gr.Textbox(value=openai_conversation, lines=10)
            openai_conversation_display.select(fn=lambda: openai_conversation_display, outputs=openai_conversation_display)
        with gr.Column():
            gr.Markdown("Gradio Conversation")
            gradio_conversation_display = gr.Textbox(value=gradio_conversation, lines=10)
            gradio_conversation_display.select(fn=lambda: gradio_conversation_display, outputs=gradio_conversation_display)



def main():
    """Main entry point for the Gradio application"""
    print("🚀 Starting Slide Generator with Stateless Chatbot Integration")
    print(f"📊 Using LLM endpoint: {config.llm_endpoint}")
    print(f"📁 Output directory: {config.output_dir}")
    
    demo.launch(
        server_name=config.gradio_host,
        server_port=config.gradio_port,
        share=config.gradio_share,
        show_error=True
    )

if __name__ == "__main__":
    main()