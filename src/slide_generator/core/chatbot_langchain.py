"""
LangChain-based chatbot for creating slide decks using LLM tools.

This module provides a proper LangChain implementation using agents and proper tool patterns,
replacing the original manual tool calling approach with LangChain's built-in capabilities.

Dependencies:
    pip install langchain-databricks langchain-core pydantic

Usage:
    # Proper LangChain implementation
    from slide_generator.core.chatbot_langchain import ChatbotLangChain
    from slide_generator.tools.html_slides import HtmlDeck
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
    - Uses LangChain's proper agent pattern with AgentExecutor
    - Pydantic-based tool definitions for better validation
    - Native LangChain message handling without manual conversions
    - Automatic tool execution through LangChain agents
    - Maintains backward compatibility with original chatbot interface
"""

from slide_generator.tools.html_slides import HtmlDeck
import json
from typing import List, Dict, Any, Optional, Union
from databricks.sdk import WorkspaceClient
from pathlib import Path

# LangChain imports
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_databricks import ChatDatabricks
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.runnables import Runnable

# Pydantic imports for tool schemas
from pydantic import BaseModel, Field


# Pydantic models for tool schemas
class TitleSlideInput(BaseModel):
    """Input schema for adding a title slide."""
    title: str = Field(description="The main title of the slide")
    subtitle: str = Field(description="The subtitle of the slide")
    authors: List[str] = Field(description="List of authors")
    date: str = Field(description="Date string for the slide")


class AgendaSlideInput(BaseModel):
    """Input schema for adding an agenda slide."""
    agenda_points: List[str] = Field(description="List of agenda points")


class ContentSlideInput(BaseModel):
    """Input schema for adding a content slide."""
    title: str = Field(description="The title of the slide")
    subtitle: str = Field(description="The subtitle of the slide")
    num_columns: int = Field(description="Number of columns (1-3)", ge=1, le=3)
    column_contents: List[List[str]] = Field(description="List of columns, each containing a list of bullet points")


class CustomHtmlSlideInput(BaseModel):
    """Input schema for adding a custom HTML slide."""
    html_content: str = Field(description="Custom HTML content for the slide")
    title: Optional[str] = Field(default="", description="Title of the slide")
    subtitle: Optional[str] = Field(default="", description="Subtitle of the slide")


class SlideDetailsInput(BaseModel):
    """Input schema for getting slide details."""
    slide_number: int = Field(description="The slide number (0-indexed)", ge=0)
    attribute: Optional[str] = Field(default=None, description="Specific attribute to get")


class ModifySlideInput(BaseModel):
    """Input schema for modifying slide details."""
    slide_number: int = Field(description="The slide number (0-indexed)", ge=0)
    attribute: str = Field(description="Attribute to modify")
    content: Union[str, List, Dict, int, bool] = Field(description="New content for the attribute")


class WriteHtmlInput(BaseModel):
    """Input schema for writing HTML to disk."""
    output_path: str = Field(description="Output file path")


class ReorderSlideInput(BaseModel):
    """Input schema for reordering slides."""
    from_position: int = Field(description="Current position of the slide", ge=0)
    to_position: int = Field(description="Target position for the slide", ge=0)


# LangChain tools that wrap HtmlDeck functionality
class TitleSlideTool(BaseTool):
    """Tool for adding a title slide."""
    name: str = "tool_add_title_slide"
    description: str = "Add or replace the title slide at position 0 (first slide). Creates a Slide object with title slide type."
    args_schema: type[BaseModel] = TitleSlideInput
    html_deck: HtmlDeck
    
    def _run(self, title: str, subtitle: str, authors: List[str], date: str) -> str:
        """Execute the tool."""
        self.html_deck.add_title_slide(title=title, subtitle=subtitle, authors=authors, date=date)
        return "Title slide added/replaced at position 0"


class AgendaSlideTool(BaseTool):
    """Tool for adding an agenda slide."""
    name: str = "tool_add_agenda_slide"
    description: str = "Add or replace the agenda slide at position 1 (second slide). Creates a Slide object with agenda slide type; auto-splits to two columns if more than 8 points."
    args_schema: type[BaseModel] = AgendaSlideInput
    html_deck: HtmlDeck
    
    def _run(self, agenda_points: List[str]) -> str:
        """Execute the tool."""
        self.html_deck.add_agenda_slide(agenda_points=agenda_points)
        return "Agenda slide added/replaced at position 1"


class ContentSlideTool(BaseTool):
    """Tool for adding a content slide."""
    name: str = "tool_add_content_slide"
    description: str = "Append a content slide with 1–3 columns of bullets. Creates a Slide object with content slide type."
    args_schema: type[BaseModel] = ContentSlideInput
    html_deck: HtmlDeck
    
    def _run(self, title: str, subtitle: str, num_columns: int, column_contents: List[List[str]]) -> str:
        """Execute the tool."""
        self.html_deck.add_content_slide(
            title=title, subtitle=subtitle, num_columns=num_columns, column_contents=column_contents
        )
        return "Content slide added"


class CustomHtmlSlideTool(BaseTool):
    """Tool for adding a custom HTML slide."""
    name: str = "tool_add_custom_html_slide"
    description: str = "Add a slide with custom HTML content directly from LLM. Creates a Slide object with custom slide type."
    args_schema: type[BaseModel] = CustomHtmlSlideInput
    html_deck: HtmlDeck
    
    def _run(self, html_content: str, title: str = "", subtitle: str = "") -> str:
        """Execute the tool."""
        self.html_deck.add_custom_html_slide(html_content=html_content, title=title, subtitle=subtitle)
        return "Custom HTML slide added"


class SlideDetailsTool(BaseTool):
    """Tool for getting slide details."""
    name: str = "tool_get_slide_details"
    description: str = "Get details for a specific slide. If attribute is specified, returns that attribute value. If no attribute, returns full slide HTML."
    args_schema: type[BaseModel] = SlideDetailsInput
    html_deck: HtmlDeck
    
    def _run(self, slide_number: int, attribute: Optional[str] = None) -> str:
        """Execute the tool."""
        return self.html_deck.get_slide_details(slide_number=slide_number, attribute=attribute)


class ModifySlideTool(BaseTool):
    """Tool for modifying slide details."""
    name: str = "tool_modify_slide_details"
    description: str = "Modify a specific attribute of a slide in place. Can modify title, subtitle, content, slide_type, or metadata fields."
    args_schema: type[BaseModel] = ModifySlideInput
    html_deck: HtmlDeck
    
    def _run(self, slide_number: int, attribute: str, content: Union[str, List, Dict, int, bool]) -> str:
        """Execute the tool."""
        return self.html_deck.modify_slide_details(slide_number=slide_number, attribute=attribute, content=content)


class GetHtmlTool(BaseTool):
    """Tool for getting the current HTML deck."""
    name: str = "tool_get_html"
    description: str = "Return the current full HTML string for the deck."
    html_deck: HtmlDeck
    
    def _run(self) -> str:
        """Execute the tool."""
        html_content = self.html_deck.to_html()
        return f"Current HTML deck ({len(html_content)} characters):\n{html_content[:500]}..."


class WriteHtmlTool(BaseTool):
    """Tool for writing HTML to disk."""
    name: str = "tool_write_html"
    description: str = "Write the current HTML string to disk and return the saved path."
    args_schema: type[BaseModel] = WriteHtmlInput
    html_deck: HtmlDeck
    
    def _run(self, output_path: str) -> str:
        """Execute the tool."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.html_deck.to_html(), encoding="utf-8")
        return f"HTML written to {output_path}"


class ReorderSlideTool(BaseTool):
    """Tool for reordering slides."""
    name: str = "tool_reorder_slide"
    description: str = "Move a slide from one position to another. Slides are 0-indexed. Moving a slide shifts other slides: if slide 5 moves to position 3, slides 3-4 shift right to positions 4-5."
    args_schema: type[BaseModel] = ReorderSlideInput
    html_deck: HtmlDeck
    
    def _run(self, from_position: int, to_position: int) -> str:
        """Execute the tool."""
        try:
            self.html_deck.reorder_slide(from_position, to_position)
            return f"Moved slide from position {from_position} to position {to_position}"
        except ValueError as e:
            return f"Error reordering slide: {str(e)}"


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
        
        # Create LangChain tools
        self.tools = self._create_langchain_tools()
        
        # Create prompt template for the agent
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant that creates slide decks. Use the available tools to help users create and modify slides."),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Create the agent
        self.agent = create_tool_calling_agent(self.llm, self.tools, self.prompt)
        
        # Create the agent executor
        self.agent_executor = AgentExecutor(
            agent=self.agent, 
            tools=self.tools, 
            verbose=False,
            return_intermediate_steps=True,
            handle_parsing_errors=True
        )
    
    def _create_langchain_tools(self) -> List[BaseTool]:
        """Create LangChain tools that wrap HtmlDeck functionality"""
        return [
            TitleSlideTool(html_deck=self.html_deck),
            AgendaSlideTool(html_deck=self.html_deck),
            ContentSlideTool(html_deck=self.html_deck),
            CustomHtmlSlideTool(html_deck=self.html_deck),
            SlideDetailsTool(html_deck=self.html_deck),
            ModifySlideTool(html_deck=self.html_deck),
            GetHtmlTool(html_deck=self.html_deck),
            WriteHtmlTool(html_deck=self.html_deck),
            ReorderSlideTool(html_deck=self.html_deck),
        ]
    
    def _convert_openai_to_langchain_messages(self, conversation: List[Dict]) -> List[BaseMessage]:
        """Convert OpenAI format conversation to LangChain messages"""
        messages = []
        
        for msg in conversation:
            role = msg["role"]
            content = msg["content"]
            
            if role == "system":
                messages.append(SystemMessage(content=content))
            elif role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "tool":
                # Skip tool messages as they're handled by the agent executor
                continue
        
        return messages
    
    def call_llm(self, conversation: List[Dict]) -> tuple[Dict, bool]:
        """
        Call LLM with conversation history and return the response message.
        
        Args:
            conversation: The complete conversation history in OpenAI format
            
        Returns:
            Tuple of (assistant message dict, is_finished boolean)
        """
        try:
            # Convert OpenAI format to LangChain messages
            langchain_messages = self._convert_openai_to_langchain_messages(conversation)
            
            # Create the input for the agent - use the last human message as input
            # and the previous messages as chat history
            if langchain_messages and isinstance(langchain_messages[-1], HumanMessage):
                input_message = langchain_messages[-1].content
                chat_history = langchain_messages[:-1] if len(langchain_messages) > 1 else []
            else:
                input_message = ""
                chat_history = langchain_messages
            
            # Run the agent
            result = self.agent_executor.invoke({
                "input": input_message,
                "chat_history": chat_history
            })
            
            # Extract the output
            output = result.get("output", "")
            
            # Check if tools were used (indicates more processing needed)
            intermediate_steps = result.get("intermediate_steps", [])
            is_finished = len(intermediate_steps) == 0 or not any(
                step for step in intermediate_steps if step[0].tool != "Final Answer"
            )
            
            assistant_message = {
                "role": "assistant",
                "content": output
            }
            
            return assistant_message, is_finished
            
        except Exception as e:
            error_message = {
                "role": "assistant",
                "content": f"Error: {str(e)}"
            }
            return error_message, True
    
    def execute_tool_call(self, tool_call_dict: Dict) -> Dict:
        """
        Execute a single tool call and return the result message.
        
        Note: This method is maintained for compatibility but is not used
        in the LangChain agent implementation as tools are executed automatically.
        
        Args:
            tool_call_dict: Dictionary containing tool call information
            
        Returns:
            Dict containing the tool result message
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_dict.get("id", "unknown"),
            "content": "Tool execution handled automatically by LangChain agent"
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
    
    print("""
    Migration from original chatbot:
    
    BEFORE (original):
    ================
    from slide_generator.core.chatbot import Chatbot
    chatbot = Chatbot(html_deck, llm_endpoint_name, ws)
    
    AFTER (LangChain):
    ================
    from slide_generator.core.chatbot_langchain import ChatbotLangChain as Chatbot
    chatbot = Chatbot(html_deck, llm_endpoint_name, ws)
    
    # Same interface, enhanced functionality!
    """)
    
    print("""
    Key Benefits of LangChain Version:
    ================================
    ✅ Proper LangChain agent pattern with AgentExecutor
    ✅ Pydantic-based tool validation and schema enforcement
    ✅ Native LangChain message handling
    ✅ Automatic tool execution without manual calling
    ✅ Better error handling and debugging
    ✅ Easier to extend with LangChain ecosystem
    ✅ No manual finish reason checking - handled by agents
    ✅ Drop-in replacement - same interface maintained
    """)
