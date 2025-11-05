# AI Slide Generator

An API-driven system that generates HTML slide decks using LLMs. The system takes natural language questions, queries structured data through Databricks Genie, and produces professional HTML presentations with data-driven insights.

## Overview

**Input**: Natural language question (e.g., "Produce a 10-page report on the consumption history of my account")

**Output**: HTML slide deck with data visualizations and narrative

**Architecture**: Agent-based system with tool-calling capabilities and MLOps integration

**Process**:
1. Agent receives question and analyzes intent
2. Agent uses `query_genie_space` tool to retrieve data from Databricks Genie
3. Agent may call tool multiple times to gather comprehensive data
4. Agent analyzes data to identify patterns and insights
5. Agent constructs coherent data-driven narrative
6. Agent generates professional HTML slides
7. MLFlow tracks execution metrics, traces, and artifacts

## Technologies

- **Python 3.10+**: Core language for robust type support and modern features
- **Databricks SDK**: Integration with Databricks LLM serving and Genie APIs
- **Databricks Genie**: SQL-based structured data retrieval with natural language interface
- **MLFlow**: Experiment tracking, metrics logging, and distributed tracing
- **FastAPI**: Lightweight, high-performance API framework for endpoints
- **Pydantic**: Data validation and settings management for type safety
- **uv**: Fast Python package manager for dependency management
- **pytest**: Testing framework for comprehensive test coverage
- **ruff**: Fast linting and formatting for code quality

### Why These Technologies?
- **Databricks LLM + Genie**: Native integration provides seamless data access and AI capabilities
- **Agent Architecture**: Modern LLM pattern with tool-calling for flexible, extensible design
- **MLFlow**: Built-in observability for debugging and experiment tracking in Databricks
- **FastAPI**: Async support and automatic API documentation generation
- **Pydantic**: Strong typing ensures data validation and reduces runtime errors
- **PyYAML**: Flexible configuration management for prompts and settings
- **uv**: Significantly faster than pip for dependency resolution

## Architecture Highlights

### Agent-Based Architecture
- **Tool-Using Agent**: LLM agent that can call tools (starting with Genie) to gather data
- **Modular Tools**: Extensible tool system with Pydantic schemas
- **Conversation Loop**: Agent decides which tools to use and when
- **MLFlow Integration**: All runs tracked with metrics, parameters, and traces
- **Observability**: Step-by-step tracing visible in Databricks workspace

### YAML-Based Configuration
- **Separation of Concerns**: Secrets in `.env`, application config in YAML files
- **Easy Customization**: Modify prompts, LLM parameters, and output settings without code changes
- **Version Control**: YAML files can be safely committed and tracked
- **Team Collaboration**: Non-technical users can adjust prompts and settings

### Singleton Databricks Client
- **Efficiency**: Single `WorkspaceClient` instance shared across agent and tools
- **Thread-Safe**: Proper locking prevents race conditions
- **Reduced Overhead**: Minimizes connection and authentication overhead
- **Simplified Testing**: Mock once, reuse everywhere
- **Flexible Authentication**: Supports multiple authentication methods:
  - **Environment variables**: Default method using `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
  - **Profile**: Use Databricks CLI profiles from `~/.databrickscfg`
  - **Direct credentials**: Pass host and token directly for programmatic access

### Configuration Examples

**config/config.yaml:**
```yaml
llm:
  endpoint: "databricks-llama-3-1-70b-instruct"
  temperature: 0.7
  max_tokens: 4096

genie:
  default_space_id: "your-genie-space-id"
  timeout: 60

mlflow:
  tracking_uri: "databricks"
  experiment_name: "/Users/<your-user>/ai-slide-generator"
  enable_tracing: true

output:
  default_max_slides: 10
  html_template: "professional"
```

**config/prompts.yaml:**
```yaml
system_prompt: |
  You are an expert data analyst with access to tools.
  Use the query_genie_space tool to gather data...
  
tool_instructions: |
  Use tools strategically to gather comprehensive data...

tools:
  - name: "query_genie_space"
    description: "Query Databricks Genie for data"
    parameters:
      type: "object"
      properties:
        query:
          type: "string"
          description: "Natural language or SQL query"
```

## Documentation

- **[PROJECT_PLAN.md](PROJECT_PLAN.md)**: Comprehensive project plan with architecture, milestones, and implementation steps
- **[pyproject.toml](pyproject.toml)**: Project configuration and dependencies

## Getting Started

### Prerequisites
- Python 3.10 or higher
- Databricks workspace with:
  - Model serving endpoint deployed
  - Genie space configured
  - Appropriate API access permissions

### Installation

1. **Clone repository:**
   ```bash
   git clone <repository-url>
   cd ai-slide-generator
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Activate virtual environment:**
   ```bash
   source .venv/bin/activate
   ```

4. **Configure environment:**
   
   The project uses a two-tier configuration system:
   
   **a) Secrets (Environment Variables):**
   ```bash
   cp .env.example .env
   # Edit .env with your Databricks credentials
   ```
   
   Required in `.env`:
   - `DATABRICKS_HOST`: Your Databricks workspace URL
   - `DATABRICKS_TOKEN`: Personal access token
   
   **b) Application Settings (YAML):**
   ```bash
   cp config/config.example.yaml config/config.yaml
   # Edit config/config.yaml with your settings
   ```
   
   Configure in `config/config.yaml`:
   - LLM endpoint name and parameters
   - Genie space ID
   - Output formatting options
   - API settings
   
   **c) Prompts (YAML):**
   ```bash
   # Edit config/prompts.yaml with your system prompts
   ```
   
   Customize prompts for:
   - System prompt (main instructions)
   - Intent analysis
   - Data interpretation
   - Narrative construction
   - HTML generation

### Running the Application

```bash
uvicorn src.main:app --reload
```

API will be available at `http://localhost:8000`

### Making Requests

```bash
curl -X POST http://localhost:8000/generate-slides \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Produce a 10-page report on consumption history",
    "max_slides": 10
  }'
```

## Development

### Install dev dependencies:
```bash
uv sync --extra dev
```

### Run tests:
```bash
pytest
```

### Run tests with coverage:
```bash
pytest --cov=src tests/
```

### Format and lint:
```bash
# Check code
ruff check .

# Format code
ruff format .

# Type check
mypy src/
```

## Project Structure

```
ai-slide-generator/
├── src/
│   ├── api/              # FastAPI endpoints and request/response models
│   ├── config/           # Configuration and settings management
│   ├── services/         # Core business logic (LLM, Genie, orchestration)
│   ├── prompts/          # System prompts and templates
│   ├── models/           # Data models and validation
│   └── utils/            # Shared utilities and helpers
├── tests/
│   ├── unit/             # Unit tests
│   └── integration/      # Integration tests
├── examples/             # Example questions and outputs
├── docs/                 # Additional documentation
├── pyproject.toml        # Project configuration
├── PROJECT_PLAN.md       # Detailed project plan
└── README.md             # This file
```

## Current Status

**Phase 1 - Foundation Setup**: ✅ Complete

Completed:
- ✅ Project structure and folder organization
- ✅ YAML-based configuration system (`config.yaml` and `prompts.yaml`)
- ✅ Singleton Databricks client with flexible authentication (profile, host/token, environment)
- ✅ Pydantic-based settings management with validation
- ✅ Comprehensive error handling and logging
- ✅ Pytest framework with fixtures and unit tests (15 tests passing)

**Next Phase**: Databricks Integration (LLM and Genie services) - see [PROJECT_PLAN.md](PROJECT_PLAN.md) for details

## Contributing

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for development guidelines and implementation steps.

## License

*License information to be added*

