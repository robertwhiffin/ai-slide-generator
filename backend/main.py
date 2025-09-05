"""FastAPI backend for the slide generator application."""

import html
import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Import slide generator modules
import sys
sys.path.append(str(Path(__file__).parent.parent / "src"))

from slide_generator.tools import html_slides, uc_tools
from slide_generator.core import chatbot
from slide_generator.config import config
from databricks.sdk import WorkspaceClient

# Initialize Databricks client and components
ws = WorkspaceClient(product='slide-generator', profile='e2-demo-field-eng-aws')

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

# Initialize FastAPI app
app = FastAPI(title="Slide Generator API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global conversation state (in production, use proper session management)
conversations: Dict[str, Dict] = {}

# Pydantic models for API requests/responses
class ChatMessage(BaseModel):
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatResponse(BaseModel):
    messages: List[ChatMessage]
    session_id: str

class SlidesResponse(BaseModel):
    html: str

def openai_to_api_message(openai_msg: Dict) -> List[ChatMessage]:
    """Convert OpenAI format message to API ChatMessage format"""
    if openai_msg["role"] == "system":
        return []  # Don't display system messages
    
    elif openai_msg["role"] == "user":
        return [ChatMessage(role="user", content=openai_msg["content"])]
    
    elif openai_msg["role"] == "assistant":
        messages = []
        if "tool_calls" in openai_msg and openai_msg["content"]:
            # Assistant with tool calls
            messages.append(ChatMessage(role="assistant", content=openai_msg["content"]))
            tool_content = f"Calling tool {openai_msg['tool_calls'][0]['function']['name']} with arguments {openai_msg['tool_calls'][0]['function']['arguments']}"
            messages.append(ChatMessage(
                role="assistant",
                content=tool_content,
                metadata={"title": "🔧 Using a tool"}
            ))
        else:
            # Regular assistant message
            messages.append(ChatMessage(role="assistant", content=openai_msg["content"]))
        return messages
    
    elif openai_msg["role"] == "tool":
        # Tool result - display as assistant message with special formatting
        return [ChatMessage(
            role="assistant", 
            content=f"✅ {openai_msg['content']}",
            metadata={"title": "🔧 Tool result"}
        )]
    
    return []

def get_or_create_conversation(session_id: str) -> Dict:
    """Get or create conversation for session"""
    if session_id not in conversations:
        conversations[session_id] = {
            "openai_conversation": [{"role": "system", "content": config.system_prompt}],
            "api_conversation": []
        }
    return conversations[session_id]

def update_conversations_with_openai_message(session_id: str, openai_msg: Dict):
    """Add OpenAI message to both conversation lists"""
    conv = get_or_create_conversation(session_id)
    conv["openai_conversation"].append(openai_msg)
    api_messages = openai_to_api_message(openai_msg)
    conv["api_conversation"].extend(api_messages)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Slide Generator API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Handle chat messages and return conversation history"""
    try:
        session_id = request.session_id
        user_input = request.message.strip()
        
        if not user_input:
            conv = get_or_create_conversation(session_id)
            return ChatResponse(messages=conv["api_conversation"], session_id=session_id)
        
        # Add user message to conversation
        user_msg_openai = {"role": "user", "content": user_input}
        update_conversations_with_openai_message(session_id, user_msg_openai)
        
        # Start background processing
        import threading
        thread = threading.Thread(target=process_conversation_sync, args=(session_id,))
        thread.daemon = True
        thread.start()
        
        # Return immediately with user message added
        conv = get_or_create_conversation(session_id)
        return ChatResponse(messages=conv["api_conversation"], session_id=session_id)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

def process_conversation_sync(session_id: str):
    """Process conversation in background thread"""
    try:
        print(f"Starting async processing for session {session_id}")
        conv = get_or_create_conversation(session_id)
        max_iterations = 30
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            print(f"Iteration {iteration} - calling LLM")
            
            # Call LLM with OpenAI format conversation
            assistant_response, stop = chatbot_instance.call_llm(conv["openai_conversation"])
            print(f"LLM response received, stop={stop}")
            
            # Add assistant response to conversations
            update_conversations_with_openai_message(session_id, assistant_response)
            print(f"Added assistant response to conversation")
            
            # If assistant used tools, execute them
            if "tool_calls" in assistant_response:
                print(f"Assistant wants to use {len(assistant_response['tool_calls'])} tools")
                for tool_call in assistant_response["tool_calls"]:
                    print(f"Executing tool: {tool_call['function']['name']}")
                    # Execute the tool
                    tool_result = chatbot_instance.execute_tool_call(tool_call)
                    
                    # Add tool result to conversations
                    update_conversations_with_openai_message(session_id, tool_result)
                    print(f"Added tool result to conversation")
            
            # Check if we're done
            if stop:
                print(f"Conversation complete after {iteration} iterations")
                break
                
            # Safety check
            if iteration >= max_iterations:
                print(f"Reached maximum iterations ({max_iterations})")
                error_msg = {"role": "assistant", "content": "Reached maximum iterations. Please try a simpler request."}
                update_conversations_with_openai_message(session_id, error_msg)
                break
                
        print(f"Async processing complete for session {session_id}")
    except Exception as e:
        print(f"Error in async processing: {e}")
        import traceback
        traceback.print_exc()

@app.get("/chat/status/{session_id}")
async def get_chat_status(session_id: str):
    """Get current conversation status and messages"""
    conv = get_or_create_conversation(session_id)
    return {
        "messages": conv["api_conversation"],
        "session_id": session_id,
        "message_count": len(conv["api_conversation"])
    }

@app.get("/slides/html", response_model=SlidesResponse)
async def get_slides_html():
    """Get current slides as HTML"""
    try:
        current_html = chatbot_instance.get_deck_html()
        return SlidesResponse(html=current_html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting slides: {str(e)}")

@app.post("/slides/refresh")
async def refresh_slides():
    """Refresh slides display"""
    try:
        current_html = chatbot_instance.get_deck_html()
        return {"html": current_html}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing slides: {str(e)}")

@app.post("/slides/reset")
async def reset_slides():
    """Reset slides to empty deck"""
    try:
        # Create new deck with same theme
        global html_deck, chatbot_instance
        html_deck = html_slides.HtmlDeck(theme=ey_theme)
        chatbot_instance = chatbot.Chatbot(
            html_deck=html_deck,
            llm_endpoint_name=config.llm_endpoint,
            ws=ws,
            tool_dict=uc_tools.UC_tools
        )
        return {"message": "Slides reset successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resetting slides: {str(e)}")

@app.post("/slides/export")
async def export_slides():
    """Export slides to file"""
    try:
        output_path = config.get_output_path("exported_slides.html")
        result = chatbot_instance.save_deck(str(output_path))
        return {"message": result, "path": str(output_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting slides: {str(e)}")

@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str):
    """Get conversation history for debugging"""
    conv = get_or_create_conversation(session_id)
    return {
        "openai_conversation": conv["openai_conversation"],
        "api_conversation": conv["api_conversation"]
    }

if __name__ == "__main__":
    print("🚀 Starting Slide Generator FastAPI Backend")
    print(f"📊 Using LLM endpoint: {config.llm_endpoint}")
    print(f"📁 Output directory: {config.output_dir}")
    
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
