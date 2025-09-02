import html
import gradio as gr
import base64
from pathlib import Path
from slide_generator.tools import html_slides, uc_tools
from slide_generator.core import chatbot
from slide_generator.config import config, get_output_path
from databricks.sdk import WorkspaceClient

ws = WorkspaceClient(product='slide-generator')

def get_logo_base64():
    """Load the EY-Parthenon logo and encode it as base64 for embedding in HTML."""
    logo_path = Path(__file__).parent.parent / "assets" / "EY-Parthenon_Logo_2021.svg"
    try:
        with open(logo_path, 'rb') as logo_file:
            logo_data = logo_file.read()
            return base64.b64encode(logo_data).decode('utf-8')
    except FileNotFoundError:
        print(f"Warning: Logo file not found at {logo_path}")
        return ""

# Initialize chatbot and conversation state with EY-Parthenon branding
ey_theme = html_slides.SlideTheme(
    bottom_right_logo_url="data:image/svg+xml;base64," + get_logo_base64(),
    bottom_right_logo_height_px=50,
    bottom_right_logo_margin_px=20
)
html_deck = html_slides.HtmlDeck(theme=ey_theme)
chatbot_instance = chatbot.Chatbot(
    html_deck=html_deck,
    llm_endpoint_name=config.llm_endpoint,
    ws=ws,
    tool_dict=uc_tools.UC_tools
    )

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
        if "tool_calls" in openai_msg and openai_msg["content"]:
            # Assistant with tool calls
            content = openai_msg["content"] 
            tool_content = f"Calling tool {openai_msg['tool_calls'][0]['function']['name']} with arguments {openai_msg['tool_calls'][0]['function']['arguments']}"
            return [
                gr.ChatMessage(
                    role="assistant",
                    content=content
                ),
                gr.ChatMessage(
                    role="assistant",
                    content=tool_content,
                    metadata={"title": "🔧 Using a tool"}
                ),
                ]
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
    if type(gradio_msg) is list:
        gradio_conversation.extend(gradio_msg)

    elif gradio_msg is not None:
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
    max_iterations = 30
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
                value="Generate a succinct report EY Parthenon. Do not generate more than 5 slides. Use the information available in your tools. Use visualisations. Include an overview slide of EY Parthenon. Think about your response.",
                lines=2,
                max_lines=5
            )
            input_box.submit(fn=handle_user_input, inputs=input_box, outputs=[chatbox, input_box])

        with gr.Column():
            gr.Markdown("## 🎯 Generated Slides")
            slides_display = gr.HTML(value=update_slides())
            with gr.Row():
                update_button = gr.Button("🔄 Refresh Slides", variant="secondary")
                reset_button = gr.Button("🔄 Reset Slides", variant="secondary")
                export_button = gr.Button("🔄 Export Slides", variant="secondary")
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
        assistant_response_textbox=gr.Textbox(value='', lines=10)
        assistant_response_textbox.select(fn=lambda: chatbot_instance.call_llm(openai_conversation)[0], inputs=assistant_response_textbox, outputs=assistant_response_textbox)


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