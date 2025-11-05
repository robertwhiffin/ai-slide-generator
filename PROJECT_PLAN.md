# AI Slide Generator - Project Plan

## Project Overview

An API-driven system that generates HTML slide decks using LLMs integrated with Databricks Genie. The system takes natural language questions from users, queries structured data through Databricks Genie, analyzes the data, and produces a coherent HTML slide presentation.

### Key Characteristics
- **API-driven**: No frontend interface
- **Agent-based**: LLM agent with tool-calling capabilities
- **Tool-driven**: Agent uses tools (starting with Genie) to gather data
- **Data-driven**: Integrates with Databricks Genie for SQL-based data retrieval
- **MLOps-enabled**: MLFlow for experiment tracking and distributed tracing
- **Output**: HTML string representing a complete slide deck

### Key Architectural Decisions

#### 1. YAML-Based Configuration Management
**Rationale**: Separate secrets from application configuration for security and flexibility

- **Secrets** (tokens, credentials) → `.env` file (gitignored)
- **Configuration** (prompts, LLM parameters, output settings) → YAML files (version controlled)
- **Benefits**:
  - Easy prompt modification without code changes
  - Version control friendly configuration
  - Team collaboration on prompts and settings
  - Clear separation of concerns
  - Quick onboarding with example files

**Files**:
- `config/config.yaml`: LLM settings, Genie config, API settings, output options
- `config/prompts.yaml`: All system prompts and templates
- `.env`: Databricks host and token only

#### 2. Singleton Databricks Client
**Rationale**: Single shared WorkspaceClient instance for efficiency and consistency

- **Implementation**: Thread-safe singleton pattern in `src/config/client.py`
- **Usage**: All services (agent, tools) use `get_databricks_client()`
- **Benefits**:
  - Reduced connection overhead
  - Consistent authentication state
  - Lower memory footprint
  - Simplified testing (mock once, use everywhere)
  - No duplicate connections

#### 3. Agent-Based Architecture with MLOps
**Rationale**: Modern LLM agent pattern with built-in observability and tracking

- **Tool-Using Agent**: LLM agent that can call functions (tools) to gather data
- **Tools**: Modular, extensible tools (starting with Genie) that agent can invoke
- **MLFlow Integration**: Track experiments, metrics, and parameters
- **Distributed Tracing**: Observe agent execution step-by-step
- **Benefits**:
  - Flexible and extensible (easy to add new tools)
  - Built-in observability for debugging
  - Experiment tracking for model optimization
  - Clean separation of concerns (agent vs tools)
  - Industry-standard pattern for LLM applications

## System Workflow

```
User Question
    ↓
Agent with System Prompt
    ↓
Agent decides to use query_genie_space tool
    ↓
Tool queries Databricks Genie → Returns Data
    ↓
Agent analyzes data (may call tool again)
    ↓
Agent constructs narrative
    ↓
Agent generates HTML slides
    ↓
HTML String Output
(All steps tracked via MLFlow + Tracing)
```

### Workflow Stages

1. **Question Reception**: User submits natural language question via API
2. **Agent Initialization**: Agent loads with system prompt and available tools
3. **Tool Selection**: Agent decides to use `query_genie_space` tool for data
4. **Data Retrieval**: Tool queries Databricks Genie space (natural language or SQL)
5. **Tool Response**: Agent receives formatted data from tool
6. **Iterative Refinement**: Agent may call tool multiple times for additional data
7. **Data Analysis**: Agent analyzes all retrieved data to identify insights
8. **Narrative Construction**: Agent builds coherent data-driven story
9. **HTML Generation**: Agent produces professional HTML slides
10. **MLFlow Logging**: Metrics, traces, and artifacts logged to Databricks
11. **Output Delivery**: Returns complete HTML string

## Technology Stack

### Core Technologies
- **Python 3.10+**: Primary language
- **Databricks SDK**: Integration with Databricks services
- **Databricks Genie API**: SQL-based data retrieval
- **Databricks LLM Serving**: AI/LLM inference
- **FastAPI**: API framework for endpoints
- **Pydantic**: Data validation and settings management

### Supporting Libraries
- **httpx**: Async HTTP client for API calls
- **Jinja2**: HTML template generation (if needed)
- **python-dotenv**: Environment variable management (secrets only)
- **PyYAML**: YAML configuration file parsing
- **pytest**: Testing framework
- **ruff**: Linting and formatting

### MLOps & Observability
- **MLFlow**: Experiment tracking, model versioning, and metrics logging
- **MLFlow Tracing**: Distributed tracing for agent execution steps
- **Databricks MLFlow Integration**: Native integration with Databricks workspace

## Folder Structure

```
ai-slide-generator/
├── .cursor/                          # Cursor IDE configuration
│   ├── rules/                        # Development rules
│   └── agents/                       # AI agent definitions
├── config/
│   ├── config.yaml                   # Main configuration file
│   ├── prompts.yaml                  # System prompts and templates
│   └── config.example.yaml           # Example configuration
├── src/
│   ├── __init__.py
│   ├── main.py                       # FastAPI application entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py               # YAML + env loader, settings object
│   │   ├── loader.py                 # YAML configuration loader
│   │   └── client.py                 # Singleton Databricks client
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py                 # API endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── agent.py                  # Tool-using agent with MLFlow/tracing
│   │   └── tools.py                  # Agent tools (Genie, etc.)
│   └── utils/
│       ├── __init__.py
│       ├── error_handling.py         # Error handling utilities
│       └── logging_config.py         # Logging configuration
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Pytest fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_agent.py
│   │   └── test_tools.py
│   └── integration/
│       ├── __init__.py
│       └── test_end_to_end.py
├── examples/
│   ├── sample_questions.json         # Example questions
│   └── sample_output.html            # Example output
├── docs/
│   ├── API.md                        # API documentation
│   ├── ARCHITECTURE.md               # Architecture details
│   └── DEPLOYMENT.md                 # Deployment guide
├── .env.example                      # Example environment variables
├── .gitignore
├── pyproject.toml                    # Project configuration
├── README.md                         # Project documentation
└── PROJECT_PLAN.md                   # This file
```

## Version Control Strategy

### Files to Commit (tracked in git)
- ✅ `config/config.yaml` - Application settings (no secrets)
- ✅ `config/prompts.yaml` - System prompts and templates
- ✅ `config/config.example.yaml` - Example configuration for onboarding
- ✅ `.env.example` - Example environment variables (no actual secrets)
- ✅ All source code (`src/`)
- ✅ All tests (`tests/`)
- ✅ Documentation (`docs/`, `README.md`, `PROJECT_PLAN.md`)
- ✅ `pyproject.toml` - Dependencies and project configuration

### Files to Ignore (in `.gitignore`)
- ❌ `.env` - Contains secrets (NEVER commit)
- ❌ `config/config.local.yaml` - Local overrides (if implemented)
- ❌ `__pycache__/` - Python bytecode
- ❌ `.venv/` - Virtual environment
- ❌ `*.pyc`, `*.pyo` - Compiled Python files
- ❌ `.pytest_cache/` - Test cache
- ❌ `.coverage` - Coverage reports
- ❌ `.DS_Store` - macOS metadata
- ❌ `*.log` - Log files

### Key Points
- **YAML config files CAN be committed** because they don't contain secrets
- **Secrets live ONLY in `.env`** which is gitignored
- This separation allows:
  - Teams to share configuration and prompts
  - Version control of prompts and settings
  - Easy onboarding (copy example files)
  - Secure secret management

## Component Breakdown

### 1. Configuration (`config/` and `src/config/`)
**Purpose**: Centralized configuration management with YAML files and singleton client

#### Root Configuration Files (`config/`)
- `config.yaml`: Main configuration file
  - LLM settings (temperature, max_tokens, model parameters)
  - API settings (port, host, timeouts)
  - Output settings (slide formatting, HTML templates)
  - Feature flags and behavior controls
- `prompts.yaml`: All system prompts and templates
  - Main system prompt
  - Intent analysis prompt
  - Data interpretation prompt
  - Narrative construction prompt
  - HTML generation prompt
- `config.example.yaml`: Example configuration for new users

#### Configuration Module (`src/config/`)
- `loader.py`: YAML configuration loader
  - `load_config()`: Load and parse config.yaml
  - `load_prompts()`: Load and parse prompts.yaml
  - `merge_with_env()`: Merge YAML with environment variables
  - Validation and schema checking
- `settings.py`: Unified settings object
  - Combines YAML configuration with environment variables
  - Pydantic-based settings for validation
  - Secrets (tokens, credentials) from environment only
  - Application settings from YAML
  - Provides single source of truth: `get_settings()`
- `client.py`: Singleton Databricks client
  - `get_databricks_client()`: Returns singleton WorkspaceClient instance
  - Initializes once on first call, reuses thereafter
  - Thread-safe implementation
  - Used by all services (LLM, Genie, etc.)

**Configuration Strategy**:
- **Secrets** (tokens, credentials): Environment variables only (`.env`)
- **Application config** (prompts, LLM params, output settings): YAML files
- **Benefits**:
  - Easy to modify prompts and parameters without code changes
  - Version control friendly (YAML can be committed, .env cannot)
  - Clear separation of secrets and configuration
  - Single Databricks client instance for efficiency

### 2. API Layer (`src/api/`)
**Purpose**: HTTP interface for the application
- `routes.py`: Endpoint definitions
  - `POST /generate-slides`: Main endpoint for slide generation
  - `GET /health`: Health check endpoint
- `models.py`: Pydantic models for requests/responses
  - Request: `{ "question": str, "max_slides": int, "genie_space_id": str }`
  - Response: `{ "html": str, "metadata": dict }`

### 3. Services (`src/services/`)
**Purpose**: Core business logic - Tool-using agent architecture

**All services use the singleton Databricks client from `src/config/client.py`**

#### `agent.py`
**Purpose**: Main tool-using agent that orchestrates slide generation
- Implements the LLM agent with tool-calling capabilities
- Manages conversation state and context
- Orchestrates the workflow: question → tools → narrative → HTML
- Integrates MLFlow for experiment tracking
- Implements tracing for observability and debugging
- Handles retry logic and error recovery
- Loads system prompts from config
- Returns final HTML slide deck

**Key Components**:
- `SlideGeneratorAgent`: Main agent class
- MLFlow experiment tracking setup
- Trace logging for each agent step
- Tool execution loop
- Response formatting

#### `tools.py`
**Purpose**: Defines tools available to the agent
- Implements Pydantic-based tool schemas
- Each tool is a function the agent can call
- Tools return structured data to the agent

**Tools**:
1. `query_genie_space`: Query Databricks Genie for data
   - Takes natural language question or SQL
   - Manages Genie conversation state
   - Returns formatted data results
   - Handles pagination and errors


### 4. Utils (`src/utils/`)
**Purpose**: Shared utilities
- `error_handling.py`: Custom exceptions and error handling
- `logging_config.py`: Structured logging setup

## Development Milestones

### Phase 1: Foundation Setup (Week 1)
**Goal**: Establish project infrastructure and basic connectivity

**Tasks**:
1. Set up project structure and dependencies
   - Create folder structure as defined
   - Update `pyproject.toml` with all dependencies (add PyYAML)
   - Install development tools (pytest, ruff, mypy)
2. Create configuration files
   - Create `config/config.yaml` with LLM, Genie, API, and output settings
   - Create `config/prompts.yaml` with placeholder prompts
   - Create `config/config.example.yaml` for onboarding
   - Create `.env.example` for secret configuration
3. Implement configuration management
   - Build `src/config/loader.py` for YAML parsing
   - Build `src/config/settings.py` for unified settings
   - Implement validation with Pydantic
4. Create singleton Databricks client
   - Implement `src/config/client.py` with thread-safe singleton
   - Add `get_databricks_client()` function
   - Verify connection works
5. Set up logging and error handling
   - Configure logging from config.yaml
   - Create custom exception classes
6. Write unit test framework
   - Set up pytest configuration
   - Create mock fixtures for Databricks client
   - Write tests for configuration loading

**Deliverables**:
- Complete project structure with all directories
- YAML configuration system working
- Singleton Databricks client functioning
- Configuration loading tested and validated
- CI/CD pipeline configured

### Phase 2: Agent & Tools Implementation (Week 2)
**Goal**: Implement tool-using agent with Databricks integration

**Tasks**:
1. Implement Genie tool (`tools.py`)
   - Define Pydantic tool schema for `query_genie_space`
   - Connect to Databricks Genie API
   - Implement conversation management
   - Test data retrieval and formatting
   - Handle errors and pagination
2. Set up MLFlow integration
   - Configure MLFlow tracking URI (Databricks workspace)
   - Create experiment for slide generation
   - Set up trace logging configuration
   - Test basic logging and tracing
3. Implement agent (`agent.py`)
   - Create `SlideGeneratorAgent` class
   - Connect to Databricks model serving endpoint
   - Implement tool-calling loop
   - Add MLFlow experiment tracking
   - Add tracing for each agent step
   - Load system prompts from config
   - Test basic agent execution

**Deliverables**:
- Working Genie tool with tests
- MLFlow tracking configured and tested
- Working agent with tool-calling capability
- Sample queries returning data via agent
- Integration test suite
- Trace logs viewable in Databricks

### Phase 3: Slide generation (Week 3)
**Goal**: Define and refine the system prompts and html constraints passed to the LLM

**Tasks**:
1. Design HTML slide templates
2. Add styling (CSS)
3. Implement data visualization embedding
4. Add chart/graph generation
5. Optimize slide layout
6. Handle various slide types (title, content, data, conclusion)

**Deliverables**:
- System returns a data driven narrative of HTML slides.

### Phase 4: Robustness & Polish (Week 5)
**Goal**: Production readiness

**Tasks**:
1. Error handling improvements
2. Retry logic for API calls
3. Performance optimization
4. Comprehensive testing
5. Documentation completion
6. Example generation
7. Deployment preparation

**Deliverables**:
- Production-ready code
- Complete documentation
- Deployment guide
- Example gallery

## Implementation Steps

### Step 1: Environment Setup
1. Create virtual environment
2. Install dependencies via `pyproject.toml` (add PyYAML)
3. Set up `.env` file with Databricks credentials (secrets only)
4. Create `config/config.yaml` from `config.example.yaml`
5. Create `config/prompts.yaml` (paste system prompt here)
6. Verify Databricks connectivity

### Step 2: Configuration Implementation
1. Create `src/config/loader.py`:
   - Implement `load_config()` to parse config.yaml
   - Implement `load_prompts()` to parse prompts.yaml
   - Implement `merge_with_env()` to combine YAML and environment
   - Add validation for required fields
2. Create `src/config/settings.py`:
   - Create Pydantic BaseSettings class
   - Load secrets from environment variables
   - Load application config from YAML via loader
   - Expose `get_settings()` function for singleton access
3. Set up logging configuration from config.yaml

### Step 3: Singleton Databricks Client
1. Create `src/config/client.py`:
   - Implement singleton pattern for WorkspaceClient
   - Create `get_databricks_client()` function
   - Initialize with credentials from settings
   - Add thread-safe locking mechanism
   - Implement lazy initialization
2. Add connection verification
3. Implement retry logic for initialization failures
4. Add error handling for authentication issues

### Step 4: Genie Tool Implementation
1. Create `src/services/tools.py`:
   - Define Pydantic schema for `query_genie_space` tool
   - Accept Databricks client (from `get_databricks_client()`)
   - Load Genie settings from settings (config.yaml)
2. Implement `query_genie_space()` function:
   - Connect to Databricks Genie API
   - Create/manage Genie conversations
   - Execute natural language or SQL queries
   - Parse and format results for agent consumption
   - Handle pagination, errors, and edge cases
3. Add comprehensive docstrings for tool parameters
4. Add unit tests with mocked Databricks client
5. Test with sample queries

### Step 5: MLFlow Integration Setup
1. Add MLFlow configuration to `config/config.yaml`:
   - Tracking URI (Databricks workspace)
   - Experiment name for slide generation - from config
   - Trace logging settings
   - Metrics to track (latency, token usage, etc.)
2. Create MLFlow initialization utility:
   - Set tracking URI to Databricks workspace
   - Create/get experiment
   - Configure trace logging
3. Test MLFlow connectivity:
   - Log test run to Databricks
   - Verify traces appear in workspace
   - Test metric and parameter logging

### Step 6: Agent Implementation
1. Create `src/services/agent.py`:
   - Create `SlideGeneratorAgent` class
   - Accept Databricks client (from `get_databricks_client()`)
   - Load LLM parameters from settings (config.yaml)
   - Load system prompts from settings (prompts.yaml)
2. Implement tool-calling loop:
   - Register available tools (from `tools.py`)
   - Send messages with tool schemas to LLM
   - Parse tool call requests from LLM
   - Execute tools and return results
   - Continue conversation until completion
3. Add MLFlow tracking:
   - Start MLFlow run for each request
   - Log parameters (question, max_slides, etc.)
   - Log metrics (execution time, token usage, etc.)
   - Log artifacts (generated HTML)
4. Add tracing:
   - Trace each agent step (tool calls, LLM responses)
   - Log input/output for each step
   - Track token usage per step
   - Enable debugging via trace logs
5. Implement `generate_slides()` method:
   - Main entry point for slide generation
   - Orchestrates: question → tool use → narrative → HTML
   - Returns final HTML string
6. Add error handling and retry logic
7. Add unit tests with mocked client and tools

### Step 7: Prompt Management
1. Define prompt structure in `config/prompts.yaml`:
   - Main system prompt (paste existing prompt here)
   - Tool use instructions
   - HTML generation guidelines
   - Narrative structure template
2. Add prompt variables/placeholders for dynamic content
3. Define tool schemas in YAML format:
   - `query_genie_space` schema
   - Input parameters and descriptions
   - Output format specifications
4. Add examples and few-shot demonstrations
5. Create helper functions in agent to load and format prompts

### Step 8: HTML Generation
1. Design base HTML template
2. Create slide templates (title, content, data, etc.)
3. Add CSS styling
4. Implement dynamic content insertion
5. Add chart/visualization support
6. Ensure responsive design

### Step 9: API Layer
1. Create FastAPI application
2. Define request/response models
3. Implement `/generate-slides` endpoint
4. Add validation and error handling
5. Implement health check endpoint
6. Add request logging

### Step 10: Testing
1. Write unit tests for tools:
   - Test `query_genie_space` with mocked Databricks client
   - Test error handling and edge cases
   - Test result formatting
2. Write unit tests for agent:
   - Mock LLM responses with tool calls
   - Mock tool execution
   - Test conversation flow
   - Test MLFlow logging calls
3. Create integration tests:
   - Test agent with real tools (mocked Databricks)
   - Test complete workflow with sample questions
   - Verify MLFlow metrics and traces
4. Build end-to-end test:
   - Use real Databricks connection (dev environment)
   - Test with actual Genie space
   - Verify HTML output quality
5. Add mock objects and fixtures:
   - Mock WorkspaceClient
   - Mock Genie API responses
   - Mock LLM completions with tool calls
   - MLFlow tracking fixtures

### Step 11: Documentation
1. Write API documentation
2. Create architecture documentation
3. Add code comments and docstrings
4. Write deployment guide
5. Create example gallery
6. Update README.md

### Step 12: Deployment Preparation
1. Create deployment scripts
2. Set up Docker container (optional)
3. Configure environment for production
4. Set up monitoring/logging
5. Create deployment documentation

## Key Technical Considerations

### Configuration Management
- **YAML-First Approach**: Application settings in YAML for easy modification
- **Environment Variables**: Secrets only, never committed to version control
- **Configuration Validation**: Pydantic models validate on load
- **Hot-Reload**: Changes to prompts.yaml can be reloaded without restart
- **Hierarchical Overrides**: Environment variables override YAML settings

### Singleton Databricks Client Pattern
- **Single Instance**: One WorkspaceClient instance shared across all services
- **Thread Safety**: Proper locking to prevent race conditions
- **Lazy Initialization**: Client created only when first requested
- **Connection Pooling**: Databricks SDK handles connection reuse internally
- **Benefits**:
  - Reduced connection overhead
  - Consistent authentication state
  - Lower memory footprint
  - Simplified testing (mock once, use everywhere)

**Implementation Pattern**:
```python
# src/config/client.py
_client_instance = None
_client_lock = threading.Lock()

def get_databricks_client() -> WorkspaceClient:
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                settings = get_settings()
                _client_instance = WorkspaceClient(
                    host=settings.databricks_host,
                    token=settings.databricks_token
                )
    return _client_instance

# Usage in agent and tools:
# agent.py
class SlideGeneratorAgent:
    def __init__(self):
        self.client = get_databricks_client()  # Reuses same instance
        self.mlflow_client = MlflowClient()
        
# tools.py  
def query_genie_space(query: str, conversation_id: Optional[str] = None) -> dict:
    client = get_databricks_client()  # Same instance as agent
    # Tool implementation...
```

### Agent Architecture
- **Tool-Using Agent**: LLM that can call tools to gather data
- **Tool Registry**: Dynamic tool registration and schema validation
- **Conversation Loop**: Agent → Tool Call → Tool Execution → Agent → Repeat
- **State Management**: Track conversation history and tool outputs
- **Prompt Engineering**: System prompts guide tool use and output generation

### MLFlow Integration
- **Experiment Tracking**: Log all slide generation runs
- **Parameters**: Track input questions, settings, model parameters
- **Metrics**: Log latency, token usage, tool calls, success rate
- **Artifacts**: Store generated HTML, intermediate outputs
- **Tracing**: Distributed traces for each agent step
- **Databricks Integration**: Native MLFlow in Databricks workspace

### Tool Implementation
- **Pydantic Schemas**: Type-safe tool definitions
- **Genie Tool**: Query Databricks Genie for data
- **Tool Results**: Structured data returned to agent
- **Error Handling**: Tools handle errors and return meaningful messages
- **Future Tools**: Extensible architecture for adding new tools

### Genie Integration (via Tool)
- **Conversation State**: Maintain Genie conversation IDs across calls
- **Query Flexibility**: Support natural language and SQL queries
- **Result Formatting**: Transform data for agent consumption
- **Error Handling**: Handle SQL errors gracefully
- **Shared Client**: Use singleton client instance

### HTML Generation
- **Template Design**: Create professional, clean layouts
- **Data Visualization**: Embed charts/graphs effectively
- **Responsive Design**: Ensure slides render well in different contexts
- **Performance**: Keep HTML lightweight and fast to render
- **Configuration**: Template settings from config.yaml

### Error Handling
- **Retry Logic**: Implement exponential backoff for API failures
- **Validation**: Validate all inputs and outputs
- **Logging**: Comprehensive logging for debugging
- **User Feedback**: Provide meaningful error messages
- **Configuration Errors**: Fail fast on invalid YAML or missing secrets

### Testing Strategy
- **Unit Tests**: Test agent and tools in isolation
- **Mock Client**: Mock `get_databricks_client()` for all service tests
- **Mock Tools**: Mock tool execution for agent tests
- **Mock LLM**: Mock LLM responses for predictable agent behavior
- **Integration Tests**: Test agent with real tools (mocked Databricks)
- **End-to-End Tests**: Test complete workflow with sample questions
- **MLFlow Tests**: Verify logging, metrics, and tracing
- **Mock Data**: Use mocked Genie responses for consistent testing
- **Configuration Tests**: Test YAML loading and validation

## Configuration Requirements

### Two-Tier Configuration System

#### 1. Environment Variables (`.env` file - for secrets only)
**Purpose**: Store sensitive credentials that should never be committed to version control

```bash
# Databricks Authentication (REQUIRED)
DATABRICKS_HOST=<workspace-url>
DATABRICKS_TOKEN=<access-token>

# Optional: Override API settings
API_PORT=8000
LOG_LEVEL=INFO
```

#### 2. YAML Configuration (`config/config.yaml` - for application settings)
**Purpose**: Store application configuration that can be version controlled

```yaml
# LLM Configuration
llm:
  endpoint: "databricks-llama-3-1-70b-instruct"  # Model serving endpoint name
  temperature: 0.7
  max_tokens: 4096
  top_p: 0.95
  timeout: 120

# Genie Configuration
genie:
  default_space_id: "01234567-89ab-cdef-0123-456789abcdef"
  timeout: 60
  max_retries: 3

# MLFlow Configuration
mlflow:
  tracking_uri: "databricks"  # Use Databricks workspace
  experiment_name: "/Users/<your-user>/ai-slide-generator"
  enable_tracing: true
  log_artifacts: true
  log_model_params: true

# API Configuration
api:
  host: "0.0.0.0"
  port: 8000
  cors_enabled: true
  request_timeout: 180

# Output Configuration
output:
  default_max_slides: 10
  min_slides: 3
  max_slides: 20
  html_template: "professional"
  include_metadata: true

# Logging Configuration
logging:
  level: "INFO"
  format: "json"
  include_request_id: true
```

#### 3. Prompts Configuration (`config/prompts.yaml`)
**Purpose**: Store all system prompts and templates for easy modification

```yaml
# Main System Prompt for Agent
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

# Tool Use Instructions
tool_instructions: |
  When you need data to answer the user's question, use the query_genie_space tool.
  
  The tool accepts:
  - query: Natural language question or SQL query
  - conversation_id: (optional) Continue previous conversation
  
  You can call the tool multiple times to gather different data or refine queries.
  
  Example:
  - First call: Get sales data for 2023
  - Second call: Get regional breakdown
  - Third call: Compare to previous year

# HTML Generation Guidelines
html_guidelines: |
  Generate HTML slides with the following structure:
  
  1. Title slide with question/topic
  2. Executive summary (key findings)
  3. Data slides (3-7 slides depending on complexity)
  4. Insights and analysis
  5. Conclusion and recommendations
  
  Requirements:
  - Use semantic HTML5
  - Include inline CSS for styling
  - Make slides print-friendly
  - Use clean, professional design
  - Include data tables or charts where appropriate
  - Maximum {max_slides} slides total

# Narrative Structure Template
narrative_template: |
  Structure your data narrative with:
  
  Introduction:
  - Context for the question
  - What data was analyzed
  
  Key Findings (3-5 main points):
  - Most important insights
  - Supporting data and evidence
  - Visual representations
  
  Analysis:
  - Trends and patterns
  - Anomalies or outliers
  - Comparisons and context
  
  Conclusion:
  - Summary of findings
  - Actionable recommendations
  - Next steps

# Tool Schemas
tools:
  - name: "query_genie_space"
    description: "Query Databricks Genie space to retrieve data using natural language or SQL"
    parameters:
      type: "object"
      properties:
        query:
          type: "string"
          description: "Natural language question or SQL query to execute"
        conversation_id:
          type: "string"
          description: "Optional conversation ID to continue a previous Genie conversation"
      required: ["query"]
```

### Configuration Loading Order
1. Load `config/config.yaml` (application defaults)
2. Load `config/prompts.yaml` (prompt templates)
3. Load `.env` file (secrets)
4. Environment variables override YAML settings if present
5. Validate combined configuration
6. Create singleton settings object

### Benefits of This Approach
- **Security**: Secrets stay in `.env` (gitignored), config can be committed
- **Flexibility**: Change prompts/parameters without code changes
- **Maintainability**: Clear separation of concerns
- **Versioning**: Track configuration changes in git
- **Collaboration**: Team can modify prompts easily

### Databricks Prerequisites
1. Model serving endpoint deployed and accessible
2. Genie space created and configured
3. Appropriate permissions for API access
4. Unity Catalog access (if required by Genie)

## Future Enhancements

### Phase 6+ (Optional)
1. **Caching Layer**: Cache common queries and results
2. **Template Library**: Multiple HTML themes/styles
3. **Export Formats**: PDF, PPTX export options
4. **Batch Processing**: Process multiple questions at once
5. **Feedback Loop**: Learn from user feedback
6. **Customization**: User-specific styling options
7. **Analytics**: Track usage and performance metrics
8. **Multi-Modal**: Support for images in slides
9. **Interactive Elements**: Add interactive data visualizations
10. **Version Control**: Track slide deck versions

## Success Criteria

### Functional Requirements
- ✅ Accept natural language questions via API
- ✅ Query Databricks Genie for relevant data
- ✅ Generate coherent narrative from data
- ✅ Produce HTML slide decks
- ✅ Return HTML string output
- ✅ Handle errors gracefully

### Non-Functional Requirements
- ✅ Response time < 60 seconds for typical query
- ✅ 80%+ test coverage
- ✅ Clear documentation for onboarding
- ✅ Modular, maintainable code structure
- ✅ Production-ready error handling
- ✅ Comprehensive logging

## Getting Started (Post-Implementation)

1. Clone repository
2. Set up virtual environment: `python -m venv venv`
3. Install dependencies: `pip install -e .`
4. Copy `.env.example` to `.env` and configure
5. Run tests: `pytest`
6. Start API: `uvicorn src.main:app --reload`
7. Send test request to `/generate-slides`

## Risk Mitigation

### Technical Risks
- **LLM Reliability**: Implement retry logic and fallbacks
- **Data Quality**: Validate Genie responses
- **Token Limits**: Implement chunking strategies
- **Performance**: Add timeout configurations

### Integration Risks
- **API Changes**: Abstract Databricks SDK interactions
- **Authentication**: Secure credential management
- **Rate Limits**: Implement rate limiting and queuing

## Maintenance Plan

### Regular Activities
- Monitor API performance metrics
- Review and optimize prompts
- Update dependencies
- Review and address technical debt
- Update documentation

### Quarterly Reviews
- Evaluate new Databricks features
- Assess performance optimizations
- Review security practices
- Update testing strategies

---

*Document Version: 1.0*
*Last Updated: November 5, 2025*
*Status: Planning Phase*

