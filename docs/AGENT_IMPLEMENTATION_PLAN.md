# LangChain Agent Implementation Plan

## Overview

This document outlines the implementation approach for `src/services/agent.py` - a simple LangChain wrapper that enables tool-using LLM capabilities with MLflow tracing integration.

**Important**: This plan uses the **official `databricks-langchain` package** (not `langchain-community`) based on the [official LangChain Databricks documentation](https://docs.langchain.com/oss/python/integrations/chat/databricks).

### Key Technologies
- **ChatDatabricks**: From `databricks-langchain` package
- **LangChain Core**: For prompts, tools, and agents
- **MLflow 3.0+**: Manual tracing (no autologging)
- **AgentExecutor**: For multi-turn tool calling

## Design Philosophy

**Keep it simple**: The agent is a thin wrapper around LangChain. The LLM does all the heavy lifting (data analysis, narrative construction, HTML generation). The agent only manages:
- LLM client setup
- Tool registration
- System prompt injection
- MLflow tracking and tracing
- Input/output handling

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    SlideGeneratorAgent                   │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   LangChain  │  │    MLflow    │  │   Databricks │  │
│  │     Model    │  │   Tracing    │  │    Client    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Registered Tools                     │   │
│  │         (query_genie_space from tools.py)        │   │
│  └──────────────────────────────────────────────────┘   │
│                                                           │
└─────────────────────────────────────────────────────────┘
         │                                         │
         ▼                                         ▼
   User Question                            HTML Slides Output
```

## Implementation Strategy

### 1. LangChain Integration

**Approach**: Use ChatDatabricks with AgentExecutor for multi-step tool calling

Based on [official LangChain Databricks documentation](https://docs.langchain.com/oss/python/integrations/chat/databricks)

**Key Components**:
- `ChatDatabricks`: LangChain's official Databricks model wrapper (from `databricks-langchain` package)
- Tool binding: Bind our Genie tool to the model via `bind_tools()`
- `AgentExecutor`: Handles multi-turn tool calling loop
- System prompt: Inject via ChatPromptTemplate
- Streaming: Optional for better UX

**Why ChatDatabricks**:
- Native integration with Databricks Foundation Model APIs
- Automatic authentication (uses DATABRICKS_HOST and DATABRICKS_TOKEN environment variables)
- If running inside Databricks workspace, authentication is automatic (no env vars needed)
- Built-in support for tool calling via `bind_tools()`
- Compatible with MLflow tracing
- Supports streaming, async, and all standard LangChain chat model features

**Why AgentExecutor**:
- Our use case requires multiple tool calls (LLM may need to query Genie multiple times)
- Need multi-turn conversation with tool results fed back to LLM
- AgentExecutor handles the tool calling loop automatically
- Simpler than manually implementing the loop

**Code Pattern** (conceptual):
```python
from databricks_langchain import ChatDatabricks
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool

# Create model
model = ChatDatabricks(
    endpoint=settings.llm.endpoint,
    temperature=settings.llm.temperature,
    max_tokens=settings.llm.max_tokens,
    # ... other params
)

# Bind tools to model
model_with_tools = model.bind_tools([genie_tool])

# Create prompt template
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("user", "{question}"),
    ("placeholder", "{agent_scratchpad}"),
])

# Create agent (simple chain)
agent = create_tool_calling_agent(model, [genie_tool], prompt)
agent_executor = AgentExecutor(agent=agent, tools=[genie_tool])

# Alternative simpler approach (if only single tool call needed):
# model_with_tools = model.bind_tools([genie_tool])
# chain = prompt | model_with_tools
# However, we use AgentExecutor because we need multi-turn tool calling
```

### 2. Tool Registration

**Approach**: Convert `query_genie_space` to LangChain StructuredTool

**Why StructuredTool**:
- Type-safe with Pydantic models
- Automatic schema generation for tool calling
- Clean integration with LangChain agents
- Error handling built-in

**Implementation Steps**:
1. Create Pydantic model for tool input schema
2. Wrap `query_genie_space` function from `tools.py`
3. Create `StructuredTool` instance with proper description
4. Register tool with LangChain agent

**Code Pattern**:
```python
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from src.services.tools import query_genie_space

class GenieQueryInput(BaseModel):
    """Input schema for Genie query tool."""
    query: str = Field(description="Natural language question or SQL query")
    conversation_id: str | None = Field(
        default=None,
        description="Optional conversation ID to continue existing conversation"
    )

# Wrap the existing function
def _query_genie_wrapper(query: str, conversation_id: str | None = None) -> str:
    """Wrapper that returns JSON string for LLM consumption."""
    result = query_genie_space(query, conversation_id)
    # Return formatted string for LLM
    return f"Data: {result['data']}\nConversation ID: {result['conversation_id']}"

genie_tool = StructuredTool.from_function(
    func=_query_genie_wrapper,
    name="query_genie_space",
    description="Query Databricks Genie for data using natural language or SQL",
    args_schema=GenieQueryInput,
)
```

### 3. MLflow Tracing (WITHOUT Autologging)

**Approach**: Manual tracing using MLflow 3.0+ tracing APIs

**Reference**: [MLflow Tracing Documentation](https://mlflow.org/docs/3.0.1/tracing/integrations/langchain)

**Why NOT autologging**:
- More control over what gets traced
- Custom attributes and metadata
- Better understanding of trace structure
- Explicit is better than implicit

**MLflow 3.0 Tracing Features**:
- `mlflow.trace()`: Context manager for manual tracing
- Automatic span creation for LangChain operations
- Custom attributes and metadata
- Integration with Databricks workspace

**Implementation Steps**:
1. Configure MLflow tracking URI (Databricks workspace)
2. Set experiment name from config
3. Use `mlflow.trace()` context manager for each generation request
4. Log custom attributes (question, max_slides, etc.)
5. LangChain operations are automatically traced within context

**Code Pattern**:
```python
import mlflow

# Configure MLflow (once at initialization)
mlflow.set_tracking_uri(settings.mlflow.tracking_uri)
mlflow.set_experiment(settings.mlflow.experiment_name)

# For each request
def generate_slides(self, question: str, max_slides: int = 10) -> str:
    """Generate HTML slides from question."""
    
    # Use mlflow.trace() context manager
    with mlflow.start_span(name="generate_slides") as span:
        # Set custom attributes
        span.set_attribute("question", question)
        span.set_attribute("max_slides", max_slides)
        span.set_attribute("model_endpoint", self.settings.llm.endpoint)
        
        try:
            # Invoke agent - LangChain operations traced automatically
            result = self.agent_executor.invoke({
                "question": question,
                "max_slides": max_slides,
            })
            
            html_output = result["output"]
            span.set_attribute("output_length", len(html_output))
            span.set_attribute("status", "success")
            
            return html_output
            
        except Exception as e:
            span.set_attribute("status", "error")
            span.set_attribute("error_message", str(e))
            raise
```

### 4. System Prompt Management

**Approach**: Load from `config/prompts.yaml` and inject via ChatPromptTemplate

**Implementation**:
1. Load system prompt from settings (which loads from YAML)
2. Use string formatting to inject variables (e.g., `{max_slides}`)
3. Create ChatPromptTemplate with system message
4. Keep prompt as simple message list for LangChain

**Code Pattern**:
```python
from langchain_core.prompts import ChatPromptTemplate, SystemMessage, HumanMessage

# Load prompt from config
system_prompt_template = settings.prompts.system_prompt

# Create prompt with variables
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt_template),
    ("human", "{question}"),
    ("placeholder", "{agent_scratchpad}"),  # For tool call history
])

# Format at runtime
formatted_prompt = prompt.format_messages(
    question=question,
    max_slides=max_slides,
)
```

### 5. Error Handling

**Strategy**: Fail fast with clear error messages

**Error Types**:
1. Configuration errors (missing settings, invalid config)
2. Databricks connection errors (auth, network)
3. LLM errors (timeout, rate limit, model errors)
4. Tool execution errors (Genie failures)
5. Output validation errors (invalid HTML, empty output)

**Implementation**:
```python
class AgentError(Exception):
    """Base exception for agent errors."""
    pass

class LLMInvocationError(AgentError):
    """Raised when LLM invocation fails."""
    pass

class ToolExecutionError(AgentError):
    """Raised when tool execution fails."""
    pass

# In generate_slides method
try:
    result = self.agent_executor.invoke(...)
except TimeoutError as e:
    raise LLMInvocationError(f"LLM request timed out: {e}") from e
except Exception as e:
    raise AgentError(f"Slide generation failed: {e}") from e
```

## Capturing LLM Thinking for Chat Interface

**Requirement**: Expose all details of LLM's thinking in a chat interface

To support this, we need to capture:
1. Each message from the LLM (including reasoning)
2. Tool calls made by the LLM
3. Tool responses
4. Intermediate steps and decisions

**Implementation Strategy**: Use `return_intermediate_steps=True` in AgentExecutor

```python
# When creating AgentExecutor
agent_executor = AgentExecutor(
    agent=agent, 
    tools=[genie_tool],
    return_intermediate_steps=True,  # KEY: Captures all steps
    verbose=True,  # Optional: logs to console
)

# Result structure with intermediate_steps
result = agent_executor.invoke({"question": question})
# result = {
#     "output": "final HTML string",
#     "intermediate_steps": [
#         (AgentAction(tool='query_genie_space', tool_input={...}), "tool output"),
#         (AgentAction(tool='query_genie_space', tool_input={...}), "tool output"),
#         ...
#     ]
# }
```

### Message Structure for Chat Interface

```python
from typing import TypedDict, Literal

class ChatMessage(TypedDict):
    """Represents a single message in the conversation."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call: dict | None  # If role=assistant and making tool call
    tool_call_id: str | None  # If role=tool
    timestamp: str

class SlideGenerationResult(TypedDict):
    """Complete result with all conversation details."""
    html: str  # Final HTML output
    messages: list[ChatMessage]  # All messages for chat interface
    metadata: dict  # Additional metadata (tokens, latency, etc.)
```

## Class Structure

```python
class SlideGeneratorAgent:
    """
    Simple LangChain agent wrapper for slide generation.
    
    This agent uses a Databricks-hosted LLM with access to tools (Genie)
    to generate HTML slide decks from natural language questions.
    
    The agent is intentionally simple - it doesn't orchestrate complex
    workflows. Instead, it relies on a well-crafted system prompt to
    guide the LLM through:
    1. Using tools to gather data
    2. Analyzing the data
    3. Constructing a narrative
    4. Generating HTML slides
    
    All operations are traced via MLflow for observability.
    All intermediate steps are captured for chat interface display.
    """
    
    def __init__(self):
        """Initialize agent with LangChain model and tools."""
        self.settings = get_settings()
        self.client = get_databricks_client()
        
        # Set up MLflow
        self._setup_mlflow()
        
        # Create LangChain components
        self.model = self._create_model()
        self.tools = self._create_tools()
        self.prompt = self._create_prompt()
        self.agent_executor = self._create_agent_executor()
    
    def _setup_mlflow(self) -> None:
        """Configure MLflow tracking and experiment."""
        pass
    
    def _create_model(self) -> ChatDatabricks:
        """Create LangChain Databricks model."""
        pass
    
    def _create_tools(self) -> list[StructuredTool]:
        """Create LangChain tools from tools.py functions."""
        pass
    
    def _create_prompt(self) -> ChatPromptTemplate:
        """Create prompt template with system prompt from config."""
        pass
    
    def _create_agent_executor(self) -> AgentExecutor:
        """
        Create agent executor with model, tools, and prompt.
        
        IMPORTANT: Set return_intermediate_steps=True to capture all
        messages for chat interface display.
        """
        pass
    
    def _format_messages_for_chat(
        self, 
        question: str,
        intermediate_steps: list[tuple],
        final_output: str
    ) -> list[dict]:
        """
        Format agent execution into chat messages.
        
        Args:
            question: User's question
            intermediate_steps: List of (AgentAction, observation) tuples
            final_output: Final HTML output
            
        Returns:
            List of chat messages for UI display
        """
        pass
    
    def generate_slides(
        self,
        question: str,
        max_slides: int = 10,
        genie_space_id: str | None = None,
    ) -> dict:
        """
        Generate HTML slides from a natural language question.
        
        Args:
            question: Natural language question about data
            max_slides: Maximum number of slides to generate
            genie_space_id: Optional Genie space ID (uses default if None)
        
        Returns:
            Dictionary containing:
                - html: HTML string containing complete slide deck
                - messages: List of all messages for chat interface
                - metadata: Execution metadata (tokens, latency, etc.)
        
        Raises:
            AgentError: If generation fails
        """
        pass
```

## Configuration Requirements

### Required Settings (from `config/config.yaml`)

```yaml
# LLM Configuration
llm:
  # Endpoint name (not URL) - can be:
  # 1. Foundation Model: "databricks-dbrx-instruct", "databricks-meta-llama-3-70b-instruct"
  # 2. Custom Model: "your-custom-endpoint-name"
  # 3. External Model: "your-proxy-endpoint-name"
  endpoint: "databricks-meta-llama-3-1-70b-instruct"
  temperature: 0.7
  max_tokens: 4096
  top_p: 0.95
  timeout: 120

# MLflow Configuration
mlflow:
  tracking_uri: "databricks"  # Use "databricks" for Databricks workspace
  experiment_name: "/Users/<user>/ai-slide-generator"
  enable_tracing: true

# Genie Configuration
genie:
  space_id: "01234567-89ab-cdef-0123-456789abcdef"
  timeout: 60
```

**Note**: The `endpoint` parameter is just the endpoint name, not a full URL. ChatDatabricks automatically uses the DATABRICKS_HOST environment variable to construct the full endpoint URL.

### Supported Databricks Endpoint Types

Per the [official documentation](https://docs.langchain.com/oss/python/integrations/chat/databricks), ChatDatabricks supports:

1. **Foundation Models**: Pre-deployed models ready to use
   - Examples: `databricks-dbrx-instruct`, `databricks-meta-llama-3-70b-instruct`, `databricks-mixtral-8x7b-instruct`
   - No setup required, available immediately in workspace
   - Tool calling supported on most models

2. **Custom Models**: Your own models deployed via MLflow
   - Deploy any model to Model Serving
   - Must have OpenAI-compatible chat input/output format
   - Full control over model and configuration

3. **External Models**: Proxy endpoints to external providers
   - Examples: OpenAI GPT-4, Claude, etc.
   - Databricks acts as proxy with unified interface
   - Credentials managed via Databricks secrets

For our implementation, we'll primarily use Foundation Models for simplicity and reliability.

### Required Prompts (from `config/prompts.yaml`)

```yaml
system_prompt: |
  You are an expert data analyst and presentation creator with access to tools.
  
  Your goal is to:
  1. Understand the user's question about data
  2. Use the query_genie_space tool to retrieve relevant data
  3. Analyze the data to identify key insights
  4. Create a compelling narrative for a slide presentation
  5. Generate professional HTML slides with the narrative and visualizations
  
  Guidelines:
  - Use tools strategically to gather data
  - Make multiple tool calls if needed to get complete information
  - Analyze data thoroughly before creating the narrative
  - Generate {max_slides} slides maximum
  - Include data visualizations where appropriate
  - Ensure slides are professional and clear
  
  Always respond with the final HTML slide deck as a complete string.
```

## Dependencies

### New Dependencies to Add

Based on the [official LangChain Databricks documentation](https://docs.langchain.com/oss/python/integrations/chat/databricks):

```toml
[project]
dependencies = [
    # Existing dependencies...
    "databricks-langchain>=0.1.0",  # Official Databricks LangChain integration
    "langchain>=0.3.0",
    "langchain-core>=0.3.0",
    "mlflow>=3.0.0",
]
```

**Important**: Use `databricks-langchain` package (not `langchain-community`) for the official, maintained Databricks integration.

### Import Structure

```python
# Standard library
from typing import Any

# Third-party
import mlflow
from databricks_langchain import ChatDatabricks  # Official package
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# Local imports
from src.config.client import get_databricks_client
from src.config.settings import get_settings
from src.services.tools import query_genie_space
```

## Testing Strategy

### Unit Tests (`tests/unit/test_agent.py`)

1. **Test Agent Initialization**
   - Mock settings, client
   - Verify MLflow setup called
   - Verify LangChain components created

2. **Test Tool Creation**
   - Verify StructuredTool created correctly
   - Verify schema matches expected format
   - Verify wrapper function works

3. **Test Prompt Creation**
   - Verify system prompt loaded from config
   - Verify variables interpolated correctly
   - Verify prompt structure correct

4. **Test Message Formatting** ⭐ NEW
   - Test `_format_messages_for_chat()` with sample intermediate steps
   - Verify user message included
   - Verify tool call messages formatted correctly
   - Verify tool response messages formatted correctly
   - Verify final assistant message included
   - Verify message order preserved
   - Verify timestamps present

5. **Test Generate Slides (Mocked LLM)**
   - Mock LangChain agent executor with intermediate_steps
   - Verify invoke called with correct params
   - Verify intermediate_steps captured
   - Verify messages formatted and returned
   - Verify MLflow tracing called
   - Verify error handling

### Integration Tests (`tests/integration/test_agent_integration.py`)

1. **Test with Mock Databricks Client**
   - Mock Genie responses
   - Mock LLM responses (with tool calls)
   - Verify end-to-end flow
   - Verify MLflow traces created
   - **Verify complete message history captured** ⭐ NEW
   - **Verify messages match expected chat format** ⭐ NEW

2. **Test Message Capture with Multiple Tool Calls** ⭐ NEW
   - Mock scenario with 2-3 Genie tool calls
   - Verify all tool calls captured in messages
   - Verify conversation flow maintained

3. **Test Error Scenarios**
   - Tool execution failure
   - LLM timeout
   - Invalid configuration

## Phase 2 Deliverables Checklist

Based on PROJECT_PLAN.md Phase 2:

- [ ] Simple LangChain wrapper created
- [ ] Connected to Databricks model serving endpoint
- [ ] Tools registered and bound to LangChain model
- [ ] MLflow experiment tracking added
- [ ] Automatic tracing enabled for LangChain (manual, not autolog)
- [ ] System prompt loaded from config
- [ ] Basic agent execution tested with LLM doing all work
- [ ] Working Genie tool with tests
- [ ] MLflow tracking configured and tested
- [ ] Sample queries returning HTML slides via agent
- [ ] Integration test suite created
- [ ] Trace logs viewable in Databricks
- [ ] **Intermediate steps captured via `return_intermediate_steps=True`** ⭐ NEW
- [ ] **All messages formatted for chat interface** ⭐ NEW
- [ ] **Message structure includes tool calls and responses** ⭐ NEW
- [ ] **Tests verify message capture and formatting** ⭐ NEW

## Implementation Steps

### Step 1: Create Basic Agent Class Structure
- Define `SlideGeneratorAgent` class
- Add `__init__` with settings and client initialization
- Add placeholder methods for setup

### Step 2: Implement MLflow Setup
- Configure tracking URI
- Set experiment name
- Enable tracing configuration

### Step 3: Implement Tool Creation
- Create Pydantic input schema
- Create tool wrapper function
- Create StructuredTool from `query_genie_space`

### Step 4: Implement Model Creation
- Create ChatDatabricks instance
- Load settings from config
- Configure temperature, max_tokens, etc.

### Step 5: Implement Prompt Creation
- Load system prompt from config
- Create ChatPromptTemplate
- Add placeholder for agent scratchpad

### Step 6: Implement Agent Executor
- Use `create_tool_calling_agent`
- Bind tools to model
- Create AgentExecutor

### Step 7: Implement generate_slides Method
- Add MLflow tracing context
- Invoke agent executor with `return_intermediate_steps=True`
- Extract intermediate steps from result
- Format messages for chat interface via `_format_messages_for_chat()`
- Handle errors
- Return structured response (html, messages, metadata)

### Step 7.5: Implement _format_messages_for_chat Method
- Parse intermediate_steps list
- Convert AgentAction and observations to chat messages
- Include tool calls and tool responses
- Add timestamps
- Maintain conversation order
- Return formatted message list

**Example Implementation**:
```python
def _format_messages_for_chat(
    self, 
    question: str,
    intermediate_steps: list[tuple],
    final_output: str
) -> list[dict]:
    """Format agent execution into chat messages."""
    messages = []
    
    # User message
    messages.append({
        "role": "user",
        "content": question,
        "timestamp": datetime.utcnow().isoformat(),
    })
    
    # Process intermediate steps
    for action, observation in intermediate_steps:
        # Assistant message with tool call
        messages.append({
            "role": "assistant",
            "content": f"Using tool: {action.tool}",
            "tool_call": {
                "name": action.tool,
                "arguments": action.tool_input,
            },
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Tool response message
        messages.append({
            "role": "tool",
            "content": str(observation),
            "tool_call_id": action.tool,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    # Final assistant message with HTML
    messages.append({
        "role": "assistant",
        "content": final_output,
        "timestamp": datetime.utcnow().isoformat(),
    })
    
    return messages
```

### Step 8: Write Unit Tests
- Test each component in isolation
- Mock external dependencies
- Test error handling
- **Test message formatting**: Verify `_format_messages_for_chat()` correctly converts intermediate steps
- **Test message structure**: Ensure messages have correct roles, content, and timestamps

### Step 9: Write Integration Tests
- Test end-to-end flow
- Verify MLflow traces
- Test with mocked Databricks responses

### Step 10: Manual Testing
- Test with real Databricks connection
- Verify traces in Databricks workspace
- Test with various questions
- Validate HTML output

## Key Considerations

### 1. Simplicity Over Complexity
- Don't add orchestration logic
- Let LangChain handle tool calling loop
- Let LLM handle analysis and generation
- Agent is just glue code

### 2. Observability
- Every generation request traced
- Custom attributes for debugging
- Trace viewable in Databricks
- Metrics logged for monitoring

### 3. Error Handling
- Fail fast with clear errors
- Log errors with context
- Don't hide failures
- Provide actionable error messages

### 4. Configuration Driven
- All settings from YAML
- Easy to modify without code changes
- Prompts version controlled
- Secrets in environment variables

### 5. Testability
- Mock external dependencies
- Test components in isolation
- Integration tests with mocked responses
- Manual testing with real connections

## References

- [MLflow Tracing LangChain Integration](https://mlflow.org/docs/3.0.1/tracing/integrations/langchain)
- [LangChain ChatDatabricks Official Documentation](https://docs.langchain.com/oss/python/integrations/chat/databricks)
- [Databricks LangChain Package](https://python.langchain.com/docs/integrations/providers/databricks/)
- [LangChain Tool Calling Agents](https://python.langchain.com/docs/modules/agents/agent_types/tool_calling)
- [LangChain StructuredTool](https://python.langchain.com/docs/modules/tools/custom_tools)
- PROJECT_PLAN.md - Phase 2 (lines 334-364)

## API Response Format Update

The API response format will need to be updated to support the chat interface:

**Before** (simple HTML string):
```python
# Response
{"html": "<html>...</html>"}
```

**After** (structured with messages):
```python
# Response
{
    "html": "<html>...</html>",
    "messages": [
        {
            "role": "user",
            "content": "What were sales in Q4?",
            "timestamp": "2025-11-05T20:00:00Z"
        },
        {
            "role": "assistant",
            "content": "Using tool: query_genie_space",
            "tool_call": {
                "name": "query_genie_space",
                "arguments": {"query": "SELECT..."}
            },
            "timestamp": "2025-11-05T20:00:01Z"
        },
        {
            "role": "tool",
            "content": "[{...data...}]",
            "tool_call_id": "query_genie_space",
            "timestamp": "2025-11-05T20:00:03Z"
        },
        {
            "role": "assistant",
            "content": "<html>...slides...</html>",
            "timestamp": "2025-11-05T20:00:10Z"
        }
    ],
    "metadata": {
        "tokens_used": 1234,
        "latency_seconds": 10.5,
        "tool_calls": 2
    }
}
```

This structure allows a chat UI to display:
- User's question
- Each tool call the LLM makes
- Data returned from tools
- Final HTML output
- Complete conversation flow

## Future Enhancement: Streaming Support

For real-time chat interface updates, streaming can be added later:

```python
# Use astream_events for streaming
async for event in agent_executor.astream_events({"question": question}):
    if event["event"] == "on_chat_model_stream":
        # Stream token-by-token output
        yield event["data"]["chunk"]
    elif event["event"] == "on_tool_start":
        # Notify UI that tool is being called
        yield {"type": "tool_start", "tool": event["name"]}
    elif event["event"] == "on_tool_end":
        # Send tool result
        yield {"type": "tool_result", "data": event["data"]}
```

This is **not required for Phase 2** but the architecture supports it.

## Next Steps

After this plan is approved:
1. Implement `src/services/agent.py` following this plan
2. Implement `_format_messages_for_chat()` method for message formatting
3. Write unit tests in `tests/unit/test_agent.py` (including message formatting tests)
4. Write integration tests in `tests/integration/test_agent_integration.py` (including message capture tests)
5. Update API response models to include messages field
6. Manual testing with Databricks connection
7. Verify traces appear in Databricks MLflow UI
8. Verify message capture works correctly
9. Iterate on system prompts based on output quality

