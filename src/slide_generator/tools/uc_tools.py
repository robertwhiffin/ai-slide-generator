from databricks.sdk import WorkspaceClient
from unitycatalog.ai.core.base import get_uc_function_client
import openai
from unitycatalog.ai.openai.toolkit import UCFunctionToolkit
from unitycatalog.ai.core.databricks import DatabricksFunctionClient
import json


ws = WorkspaceClient(product='slide-generator')
catalog = "robert_whiffin"
schema="kpmg"
function_name = 'ftx_transcripts_ai_search'

tool_name = f'{catalog}.{schema}.{function_name}'

# Genie space configuration
space_id = "01f0837bc42a1b0281e4376d4e3d6143"
example_query = "give me ey spend by day for last 6 months"

client = DatabricksFunctionClient()
function = client.get_function_as_callable(function_name=tool_name)

def query_genie_space(question: str, space_id: str = space_id, workspace_client: WorkspaceClient = ws) -> str:
    """
    Query a Genie space using natural language and return the AI response.
    
    Args:
        question (str): The natural language question to ask Genie
        space_id (str): The ID of the Genie space to query (defaults to global space_id)
        workspace_client (WorkspaceClient): The Databricks workspace client (defaults to global ws)
    
    Returns:
        str: The AI response from Genie
        
    Example:
        >>> response = query_genie_space("give me ey spend by day for last 6 months")
        >>> print(response)
    """
    try:
        # Start a conversation with the question and wait for response
        message = workspace_client.genie.start_conversation_and_wait(
            space_id=space_id,
            content=question
        )
        
        # Return the content of the AI response
        return message.content if message.content else "No response received from Genie"
        
    except Exception as e:
        return f"Error querying Genie space: {str(e)}"

def get_genie_space_details(space_id: str = space_id, workspace_client: WorkspaceClient = ws) -> dict:
    """
    Get details about a Genie space.
    
    Args:
        space_id (str): The ID of the Genie space
        workspace_client (WorkspaceClient): The Databricks workspace client
        
    Returns:
        dict: Dictionary containing space details
    """
    try:
        space = workspace_client.genie.get_space(space_id=space_id)
        return {
            "space_id": space.id,
            "display_name": space.display_name,
            "description": space.description,
            "created_at": space.created_at,
            "updated_at": space.updated_at
        }
    except Exception as e:
        return {"error": f"Error getting space details: {str(e)}"}

def list_genie_conversations(space_id: str = space_id, workspace_client: WorkspaceClient = ws) -> list:
    """
    List conversations in a Genie space.
    
    Args:
        space_id (str): The ID of the Genie space
        workspace_client (WorkspaceClient): The Databricks workspace client
        
    Returns:
        list: List of conversations in the space
    """
    try:
        conversations_response = workspace_client.genie.list_conversations(space_id=space_id)
        return [
            {
                "conversation_id": conv.id,
                "title": conv.title,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at
            }
            for conv in conversations_response.conversations
        ] if conversations_response.conversations else []
    except Exception as e:
        return [{"error": f"Error listing conversations: {str(e)}"}]

# Example usage and testing
if __name__ == "__main__":
    # Test UC function
    print("Testing UC function...")
    result = client.execute_function(function_name=tool_name, parameters={"question": "New York"})
    print(f"UC Function result: {result}")
    
    # Test the Genie query function
    print("\nTesting Genie space query...")
    genie_result = query_genie_space(example_query)
    print(f"Question: {example_query}")
    print(f"Genie Response: {genie_result}")
    
    # Get space details
    print("\nGenie space details:")
    space_details = get_genie_space_details()
    print(json.dumps(space_details, indent=2, default=str))