"""
LangChain-based chatbot for creating slide decks using LLM tools.

This module provides a drop-in replacement for the original chatbot class,
using LangChain for LLM interactions instead of direct Databricks SDK calls.

Dependencies:
    pip install langchain-databricks langchain-core

Usage:
    # Drop-in replacement for original chatbot
    from python.chatbot.chatbot_langchain import ChatbotLangChain
    from python.tools.html_slides import HtmlDeck
    from databricks.sdk import WorkspaceClient
    
    html_deck = HtmlDeck()
    ws = WorkspaceClient()
    chatbot = ChatbotLangChain(
        html_deck=html_deck, 
        llm_endpoint_name="your-endpoint-name",
        ws=ws
    )
    
    # Same interface as original chatbot
    conversation = [{"role": "system", "content": "You are a slide assistant..."}]
    response = chatbot.call_llm(conversation)
    
Features:
    - Uses LangChain's ChatDatabricks for LLM interactions
    - Automatic tool binding and calling
    - Seamless conversion between OpenAI and LangChain message formats
    - Same interface as original chatbot for easy migration
    - Enhanced error handling and tool execution
"""

from python.tools.html_slides import HtmlDeck
import json
from typing import List, Dict, Any, Optional
from databricks.sdk import WorkspaceClient

# LangChain imports
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import Tool
from langchain_databricks import ChatDatabricks
from langchain_core.utils.function_calling import convert_to_openai_tool


class ChatbotLangChain:
    """A LangChain-powered chatbot class for creating slide decks using LLM tools"""
    
    def __init__(self, html_deck: HtmlDeck, llm_endpoint_name: str, ws: WorkspaceClient):
        """
        Initialize the chatbot with HTML deck and LLM endpoint using LangChain
        
        Args:
            html_deck: The HtmlDeck object to work with
            llm_endpoint_name: Name of the LLM endpoint to use
            ws: Databricks WorkspaceClient instance
        """
        self.html_deck = html_deck
        self.llm_endpoint_name = llm_endpoint_name
        self.ws = ws
        
        # Initialize LangChain ChatDatabricks
        self.llm = ChatDatabricks(
            endpoint=llm_endpoint_name,
            databricks_workspace_client=ws
        )
        
        # Convert HTML deck tools to LangChain tools
        self.langchain_tools = self._create_langchain_tools()
        
        # Bind tools to the LLM
        self.llm_with_tools = self.llm.bind_tools(self.langchain_tools)
    
    def _create_langchain_tools(self) -> List[Tool]:
        """Convert HtmlDeck tools to LangChain tool format"""
        langchain_tools = []
        
        for tool_spec in self.html_deck.TOOLS:
            function_spec = tool_spec["function"]
            tool_name = function_spec["name"]
            tool_description = function_spec["description"]
            
            # Create a LangChain tool
            langchain_tool = Tool(
                name=tool_name,
                description=tool_description,
                func=lambda args, name=tool_name: self._execute_tool_by_name(name, args)
            )
            
            # Add the OpenAI schema for proper tool calling
            langchain_tool.args_schema = None  # LangChain will infer from OpenAI format
            langchain_tool._openai_tool_spec = tool_spec
            
            langchain_tools.append(langchain_tool)
        
        return langchain_tools
    
    def _execute_tool_by_name(self, tool_name: str, args: str) -> str:
        """Execute a tool by name with string arguments"""
        try:
            # Parse arguments if they're a string
            if isinstance(args, str):
                function_args = json.loads(args)
            else:
                function_args = args
            
            return self._execute_tool_from_dict(tool_name, function_args)
        except Exception as e:
            return f"Error executing tool {tool_name}: {str(e)}"
    
    def _execute_tool_from_dict(self, function_name: str, function_args: Dict) -> str:
        """Execute a tool call from dictionary format"""
        if function_name == "tool_add_title_slide":
            self.html_deck.add_title_slide(
                title=function_args["title"], 
                subtitle=function_args["subtitle"], 
                authors=function_args["authors"], 
                date=function_args["date"]
            )
            return "Title slide added/replaced at position 0"
        
        elif function_name == "tool_add_agenda_slide":
            self.html_deck.add_agenda_slide(agenda_points=function_args["agenda_points"])
            return "Agenda slide added/replaced at position 1"
        
        elif function_name == "tool_add_content_slide":
            self.html_deck.add_content_slide(
                title=function_args["title"],
                subtitle=function_args["subtitle"],
                num_columns=function_args["num_columns"],
                column_contents=function_args["column_contents"]
            )
            return "Content slide added"
        
        elif function_name == "tool_get_html":
            html_content = self.html_deck.to_html()
            return f"Current HTML deck ({len(html_content)} characters):\n{html_content[:500]}..."
        
        elif function_name == "tool_write_html":
            from pathlib import Path
            output_path = Path(function_args["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(self.html_deck.to_html(), encoding="utf-8")
            return f"HTML written to {output_path}"
        
        elif function_name == "tool_reorder_slide":
            from_pos = function_args["from_position"]
            to_pos = function_args["to_position"]
            try:
                self.html_deck.reorder_slide(from_pos, to_pos)
                return f"Moved slide from position {from_pos} to position {to_pos}"
            except ValueError as e:
                return f"Error reordering slide: {str(e)}"
        
        else:
            return f"Unknown tool: {function_name}"
    
    def _convert_openai_to_langchain_messages(self, conversation: List[Dict]) -> List[BaseMessage]:
        """Convert OpenAI format conversation to LangChain messages"""
        messages = []
        
        for msg in conversation:
            role = msg["role"]
            content = msg["content"]
            
            if role == "system":
                # LangChain doesn't have a SystemMessage in the same way, 
                # so we'll include it as the first message or in the prompt
                messages.append(HumanMessage(content=f"System: {content}"))
            elif role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                if "tool_calls" in msg:
                    # Assistant message with tool calls
                    ai_msg = AIMessage(
                        content=content,
                        tool_calls=[
                            {
                                "name": tc["function"]["name"],
                                "args": json.loads(tc["function"]["arguments"]),
                                "id": tc["id"]
                            }
                            for tc in msg["tool_calls"]
                        ]
                    )
                    messages.append(ai_msg)
                else:
                    # Regular assistant message
                    messages.append(AIMessage(content=content))
            elif role == "tool":
                # Tool result message
                messages.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", "unknown")
                ))
        
        return messages
    
    def _convert_langchain_to_openai_message(self, message: BaseMessage) -> Dict:
        """Convert LangChain message back to OpenAI format"""
        if isinstance(message, AIMessage):
            result = {
                "role": "assistant",
                "content": message.content or ""
            }
            
            # Handle tool calls
            if hasattr(message, 'tool_calls') and message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"])
                        }
                    }
                    for i, tc in enumerate(message.tool_calls)
                ]
            
            return result
        else:
            # Fallback for other message types
            return {
                "role": "assistant",
                "content": str(message.content)
            }
    
    def call_llm(self, conversation: List[Dict]) -> Dict:
        """
        Call LLM with conversation history and return the response message.
        
        Args:
            conversation: The complete conversation history in OpenAI format
            
        Returns:
            Dict containing the assistant's response message or error
        """
            # Convert OpenAI format to LangChain messages
        langchain_messages = self._convert_openai_to_langchain_messages(conversation)
        
        # Call LangChain LLM with tools
        response = self.llm_with_tools.invoke(langchain_messages)
        
        # Convert response back to OpenAI format
        assistant_message = self._convert_langchain_to_openai_message(response)
        # this isnt working, langchain uses a different format for the response
        
        return assistant_message, response.choices[0].finish_reason == "stop"

    
    def execute_tool_call(self, tool_call_dict: Dict) -> Dict:
        """
        Execute a single tool call and return the result message.
        
        Args:
            tool_call_dict: Dictionary containing tool call information
            
        Returns:
            Dict containing the tool result message
        """
        function_name = tool_call_dict["function"]["name"]
        function_args = json.loads(tool_call_dict["function"]["arguments"])
        
        result = self._execute_tool_from_dict(function_name, function_args)
        
        return {
            "role": "tool",
            "tool_call_id": tool_call_dict["id"],
            "content": result
        }
    
    def get_html_deck(self) -> HtmlDeck:
        """Get the current HTML deck object"""
        return self.html_deck
    
    def get_deck_html(self) -> str:
        """Get the current HTML content of the deck"""
        return self.html_deck.to_html()
    
    def save_deck(self, output_path: str) -> str:
        """Save the deck to a file"""
        try:
            from pathlib import Path
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(self.html_deck.to_html(), encoding="utf-8")
            return f"Deck saved to {output_path}"
        except Exception as e:
            return f"Error saving deck: {str(e)}"


# Alias for backward compatibility
Chatbot = ChatbotLangChain


# Example usage and migration guide
if __name__ == "__main__":
    """
    Example usage and migration demonstration
    """
    print("LangChain Chatbot Example")
    print("=" * 40)
    
    # This would replace:
    # from python.chatbot.chatbot import Chatbot
    # 
    # With:
    # from python.chatbot.chatbot_langchain import ChatbotLangChain as Chatbot
    
    print("""
    Migration from original chatbot:
    
    BEFORE (original):
    ================
    from python.chatbot.chatbot import Chatbot
    chatbot = Chatbot(html_deck, llm_endpoint_name, ws)
    
    AFTER (LangChain):
    ================
    from python.chatbot.chatbot_langchain import ChatbotLangChain as Chatbot
    chatbot = Chatbot(html_deck, llm_endpoint_name, ws)
    
    # Same interface, enhanced functionality!
    """)
    
    print("""
    Key Benefits of LangChain Version:
    ================================
    ✅ Native LangChain integration
    ✅ Better tool handling and validation
    ✅ Enhanced error handling
    ✅ Easier to extend with LangChain ecosystem
    ✅ More robust message format conversion
    ✅ Drop-in replacement - same interface
    """)
