from slide_generator.tools.html_slides import HtmlDeck
import json
from typing import List, Dict
from databricks.sdk import WorkspaceClient


class Chatbot:
    """A chatbot class for creating slide decks using LLM tools"""
    
    def __init__(
            self,
            html_deck: HtmlDeck,
            llm_endpoint_name: str,
            ws: WorkspaceClient,
            tool_dict: List[Dict] = None
            ):
        """
        Initialize the chatbot with HTML deck and LLM endpoint
        
        Args:
            html_deck: The HtmlDeck object to work with
            llm_endpoint_name: Name of the LLM endpoint to use
            ws: WorkspaceClient object
            tool_dict: Dictionary of tools to use. 
                This is a dictionary of dictionaries, each containing an llm tool description and a callable. For example {function_name: {description: FUNCTION_DESCRIPTION, function: callable}}. The description must be like
                {
                    "type": "function",
                    "function": {
                    "name": FUNCTION_NAME,
                    "description": FUNCTION_DESCRIPTION,
                    "parameters": {
                        "type": "object",
                        "properties": {
                        "title": { "type": "string" },
                        "subtitle": { "type": "string" },
                        "authors": { "type": "array", "items": { "type": "string" } },
                        "date": { "type": "string" }
                        },
                        "required": ["title", "subtitle", "authors", "date"],
                        "additionalProperties": False
                    }
                    }
                }
        """

        self.html_deck = html_deck
        self.llm_endpoint_name = llm_endpoint_name
        # Add the tools from the tool_dict to the tools list
        self.tools = self.html_deck.TOOLS
        self.tools.extend([_['description'] for _ in tool_dict.values()])
        self.tool_dict = tool_dict
        
        
        # Initialize Databricks client
        self.ws = ws
        self.model_serving_client = self.ws.serving_endpoints.get_open_ai_client()
    
    def _call_llm(self, conversation: List[Dict], tools: List[Dict]):
        """Make a call to the LLM with the given conversation and tools"""
        try:
            response = self.model_serving_client.chat.completions.create(
                model=self.llm_endpoint_name,
                tools=tools,
                messages=conversation,
            )
            return response, None
        except Exception as e:
            return None, f"Error calling LLM: {str(e)}"
    

    
    def call_llm(self, conversation: List[Dict]) -> Dict:
        """
        Call LLM with conversation history and return the response message.
        
        Args:
            conversation: The complete conversation history
            
        Returns:
            Dict containing the assistant's response message or error
        """
        # Get tools from the HtmlDeck object
        tools = self.html_deck.TOOLS
        
        # Call the LLM
        response, error = self._call_llm(conversation, tools)
        if error:
            return {"role": "assistant", "content": f"Error: {error}"}
        
        # Extract the message from the response
        message = response.choices[0].message
        
        # Create the assistant message to add to conversation
        if message.tool_calls:
            # Assistant is requesting tool execution
            assistant_message = {
                "role": "assistant", 
                "content": message.content if message.content else f"Using tool {message.tool_calls[0].function.name}",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    for tool_call in message.tool_calls
                ]
            }
        else:
            # Regular assistant message
            assistant_message = {
                "role": "assistant",
                "content": message.content if message.content else "I'm processing your request."
            }
        
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
            return f"Current HTML deck ({len(self.html_deck.to_html())} characters):\n{self.html_deck.to_html()[:500]}..."
        
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
            try:
                return self.tool_dict[function_name]["function"](**function_args)
            except KeyError as e:
                return f"Unknown tool: {function_name}"
            except Exception as e:
                return f"Error executing {function_name}: {str(e)}"


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
    

