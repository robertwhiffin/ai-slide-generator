# AI Slide Generator - Project Plan

## Project Overview

An API-driven system that generates HTML slide decks using LLMs integrated with Databricks Genie. The system takes natural language questions from users, queries structured data through Databricks Genie, analyzes the data, and produces a coherent HTML slide presentation.

### Key Characteristics
- **API-driven**: No frontend interface
- **LLM-powered**: Uses Databricks-served LLM for intelligence
- **Data-driven**: Integrates with Databricks Genie for SQL-based data retrieval
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
- **Usage**: All services (LLM, Genie, etc.) use `get_databricks_client()`
- **Benefits**:
  - Reduced connection overhead
  - Consistent authentication state
  - Lower memory footprint
  - Simplified testing (mock once, use everywhere)
  - No duplicate connections

## System Workflow

```
User Question
    ↓
System Prompt + LLM
    ↓
Intent Understanding & Data Planning
    ↓
Databricks Genie SQL Queries
    ↓
Data Retrieval & Analysis
    ↓
Narrative Construction
    ↓
HTML Slide Generation
    ↓
HTML String Output
```

### Workflow Stages

1. **Question Reception**: User submits natural language question
2. **Intent Analysis**: LLM interprets question and determines data requirements
3. **Data Retrieval**: System queries Databricks Genie space via SQL
4. **Data Analysis**: LLM analyzes retrieved data to understand patterns/insights
5. **Narrative Building**: LLM constructs coherent data-driven story
6. **Slide Generation**: LLM produces HTML slides with visualizations and content
7. **Output Delivery**: Returns complete HTML string

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
│   │   ├── llm_service.py            # Databricks LLM integration
│   │   ├── genie_service.py          # Databricks Genie integration
│   │   └── slide_generator.py        # Orchestration service
│   └── utils/
│       ├── __init__.py
│       ├── error_handling.py         # Error handling utilities
│       └── logging_config.py         # Logging configuration
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Pytest fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_llm_service.py
│   │   ├── test_genie_service.py
│   │   └── test_slide_generator.py
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
**Purpose**: Core business logic

**All services use the singleton Databricks client from `src/config/client.py`**

#### `llm_service.py`
- Interface to Databricks LLM serving
- Initialization:
  - `__init__()`: Receives Databricks client via dependency injection
  - Uses `get_databricks_client()` from `src/config/client.py`
- Methods:
  - `generate_completion(prompt, tools)`: Send prompts to LLM
  - `stream_completion()`: Stream responses if needed
  - Handle function calling for Genie integration
- Configuration:
  - LLM parameters loaded from `config.yaml`
  - Prompts loaded from `prompts.yaml` via settings

#### `genie_service.py`
- Interface to Databricks Genie
- Initialization:
  - `__init__()`: Receives Databricks client via dependency injection
  - Uses same `get_databricks_client()` instance as LLM service
- Methods:
  - `create_conversation()`: Initialize Genie conversation
  - `send_message(conversation_id, message)`: Send SQL request
  - `get_query_results(message_id)`: Retrieve data
  - `format_results_for_llm()`: Transform data for LLM consumption
- Configuration:
  - Genie space ID and settings from `config.yaml`

#### `slide_generator.py`
- Orchestrates the entire workflow
- Coordinates between LLM and Genie services
- Methods:
  - `generate_slides(question)`: Main entry point
  - `_analyze_intent(question)`: Understand what data is needed
  - `_retrieve_data(data_requirements)`: Get data from Genie
  - `_analyze_data(raw_data)`: Process and understand data
  - `_generate_narrative(data_insights)`: Create story
  - `_create_html_slides(narrative)`: Produce final HTML
- Configuration:
  - Workflow settings and output formats from `config.yaml`
  - All prompts loaded from `prompts.yaml`

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

### Phase 2: Databricks Integration (Week 2)
**Goal**: Integrate with Databricks LLM and Genie

**Tasks**:
1. Implement LLM service
   - Connect to Databricks model serving endpoint
   - Test basic completions
   - Implement function calling if needed
2. Implement Genie service
   - Connect to Genie space
   - Test conversation creation
   - Test data retrieval
   - Implement result formatting
3. Integrate LLM with Genie via a tool

**Deliverables**:
- Working LLM service with tests
- Working Genie service with tests
- Sample queries returning data
- Integration test suite

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

### Step 4: LLM Service
1. Create `src/services/llm_service.py`:
   - Accept Databricks client in `__init__()` (from `get_databricks_client()`)
   - Connect to Databricks model serving endpoint
   - Load LLM parameters from settings (config.yaml)
   - Load prompts from settings (prompts.yaml)
2. Implement `generate_completion()` method
3. Handle response parsing
4. Add support for function calling (for Genie integration)
5. Implement token counting/management
6. Add unit tests with mocked client

### Step 5: Genie Service
1. Create `src/services/genie_service.py`:
   - Accept same Databricks client in `__init__()` (singleton instance)
   - Connect to Databricks Genie API
   - Load Genie settings from settings (config.yaml)
2. Implement conversation management
3. Build SQL query execution flow
4. Parse and format results
5. Handle pagination if needed
6. Add result caching (optional)
7. Add unit tests with mocked client

### Step 6: Prompt Management
1. Define prompt structure in `config/prompts.yaml`:
   - Main system prompt (paste existing prompt here)
   - Intent analysis template
   - Data interpretation template
   - Narrative construction template
   - HTML generation template
2. Add prompt variables/placeholders for dynamic content
3. Define function calling schemas for Genie in prompts.yaml
4. Add examples and few-shot demonstrations in prompts
5. Create helper functions in services to load and format prompts

### Step 7: Orchestration Service
1. Implement main `generate_slides()` method
2. Build intent analysis stage
3. Connect to Genie for data retrieval
4. Implement data analysis logic
5. Build narrative construction
6. Create HTML generation stage
7. Add state management between stages

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
1. Write unit tests for each service
2. Create integration tests for workflows
3. Build end-to-end test with sample questions
4. Add mock objects for external dependencies
5. Implement test fixtures

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

# Usage in services:
# llm_service.py
class LLMService:
    def __init__(self):
        self.client = get_databricks_client()  # Reuses same instance
        
# genie_service.py  
class GenieService:
    def __init__(self):
        self.client = get_databricks_client()  # Same instance as LLM
```

### LLM Integration
- **Function Calling**: Use for structured Genie queries
- **Context Management**: Track conversation state across stages
- **Token Limits**: Monitor and manage token usage
- **Streaming**: Consider streaming for long responses
- **Prompt Loading**: Load prompts from YAML, format with variables

### Genie Integration
- **Conversation State**: Maintain Genie conversation IDs
- **Query Optimization**: Ensure efficient SQL generation
- **Result Formatting**: Transform data for LLM consumption
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
- **Unit Tests**: Test each component in isolation
- **Mock Client**: Mock `get_databricks_client()` for all service tests
- **Integration Tests**: Test service interactions
- **End-to-End Tests**: Test complete workflows
- **Mock Data**: Use mocked responses for consistent testing
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
# Main System Prompt
system_prompt: |
  You are an expert data analyst and presentation creator...
  [Full system prompt here]

# Stage-Specific Prompts
intent_analysis: |
  Analyze the following question and determine:
  1. What data is needed
  2. What SQL queries might be required
  3. Expected output structure
  
  Question: {question}

data_interpretation: |
  Given the following data, identify key insights:
  Data: {data}
  
  Focus on:
  - Trends and patterns
  - Anomalies
  - Actionable insights

narrative_construction: |
  Create a coherent narrative for a slide deck using these insights:
  {insights}
  
  Structure the narrative with:
  - Introduction
  - Key findings (3-5 points)
  - Conclusion and recommendations

html_generation: |
  Generate HTML slides based on this narrative:
  {narrative}
  
  Requirements:
  - Professional styling
  - Clear data visualizations
  - {max_slides} slides maximum

# Function Calling Schema
genie_function_schema:
  name: "query_genie"
  description: "Query Databricks Genie space for data"
  parameters:
    type: "object"
    properties:
      query:
        type: "string"
        description: "Natural language query or SQL"
      conversation_id:
        type: "string"
        description: "Optional conversation ID to continue"
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

