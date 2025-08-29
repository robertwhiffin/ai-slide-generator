from databricks.sdk import WorkspaceClient
from unitycatalog.ai.core.databricks import DatabricksFunctionClient
import pandas as pd
ws = WorkspaceClient(product='slide-generator', profile='e2-demo-field-eng-aws')

space_id = "01f0837bc42a1b0281e4376d4e3d6143"
example_query = "give me ey spend by day for last 6 months"

def query_genie_space(question: str, space_id: str = space_id, workspace_client: WorkspaceClient = ws) -> str:

    response = workspace_client.genie.start_conversation_and_wait(
        space_id=space_id,
        content=question
    )

    conversation_id = response.conversation_id
    message_id = response.message_id
    attachment_ids = [_.attachment_id for _ in response.attachments]

    response = workspace_client.genie.get_message_attachment_query_result(
        space_id=space_id,
        conversation_id=conversation_id,
        message_id=message_id,
        attachment_id=attachment_ids[0]
    )
    response = response.as_dict()['statement_response']
    columns = [_['name'] for _ in response['manifest']['schema']['columns']]
    data = response['result']['data_array']
    df = pd.DataFrame(data, columns=columns)
    output = df.to_json(orient='records')
    
    return output


vs_tool = "tariq_yaaqba.rag_demo.similarity_vector_search"
client = DatabricksFunctionClient(
    profile='e2-demo-field-eng-aws'
)
def retrieval_tool(question: str) -> str:
    response = client.execute_function(function_name=vs_tool, parameters={"question": question})
    content =response.value
    return content


UC_tools = {
    "retrieval_tool": {
        "description": 
{
"type": "function",
"function": {
"name": "retrieval_tool",
"description": "Retrieves information from a vector search index containing information about the company EY",
"parameters": {
"type": "object",
"properties": {
"question": { "type": "string" }
},
"required": ["question"],
"additionalProperties": False
}
}},
        "function": retrieval_tool
        }
    ,
    "query_genie_space": {
        "description": 
{
"type": "function",
"function": {
"name": "query_genie_space",
"description": "Sends a question to a Databricks Genie space and returns the response. A Genie space is a text2sql tool. This space contains structured data about the spend ",
"parameters": {
"type": "object",
"properties": {
"question": { "type": "string" }
},
"required": ["question"],
"additionalProperties": False
},
}},
        "function": query_genie_space
    
}
    }