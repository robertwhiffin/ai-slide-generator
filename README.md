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
- **LangChain**: Agent framework for tool-calling and multi-step workflows
- **databricks-langchain**: Official Databricks LangChain integration for ChatDatabricks
- **Databricks SDK**: Integration with Databricks LLM serving and Genie APIs
- **Databricks Genie**: SQL-based structured data retrieval with natural language interface
- **MLflow 3.0+**: Experiment tracking, metrics logging, and distributed tracing
- **FastAPI**: Lightweight, high-performance API framework for endpoints
- **Pydantic**: Data validation and settings management for type safety
- **BeautifulSoup4**: HTML parsing for slide deck manipulation
- **lxml**: Fast HTML parser backend for BeautifulSoup
- **uv**: Fast Python package manager for dependency management
- **pytest**: Testing framework for comprehensive test coverage
- **ruff**: Fast linting and formatting for code quality

### Why These Technologies?
- **LangChain + ChatDatabricks**: Official agent framework with native Databricks support for tool-calling
- **Databricks LLM + Genie**: Native integration provides seamless data access and AI capabilities
- **Agent Architecture**: Modern LLM pattern with tool-calling for flexible, extensible design
- **MLflow 3.0**: Manual tracing with custom spans for complete observability
- **FastAPI**: Async support and automatic API documentation generation
- **Pydantic**: Strong typing ensures data validation and reduces runtime errors
- **BeautifulSoup4**: Robust HTML parsing that handles AI-generated slides with varying structure
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
- **[SLIDE_PARSER_DESIGN.md](SLIDE_PARSER_DESIGN.md)**: Detailed slide parser design and implementation specifications
- **[docs/AGENT_IMPLEMENTATION_PLAN.md](docs/AGENT_IMPLEMENTATION_PLAN.md)**: Detailed agent implementation specifications
- **[docs/IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md)**: Summary of Phase 2 implementation with testing guide
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
   
   **Option A: Using uv (recommended - faster):**
   ```bash
   uv sync
   ```
   
   **Option B: Using pip:**
   ```bash
   # Create virtual environment
   python -m venv .venv
   source .venv/bin/activate
   
   # Install core dependencies
   pip install -r requirements.txt
   
   # Install development dependencies (for testing)
   pip install -r requirements-dev.txt
   
   # Or install from pyproject.toml with dev dependencies
   pip install -e ".[dev]"
   ```

3. **Activate virtual environment (if not already active):**
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

### Using the Slide Parser

The slide parser allows you to parse, manipulate, and reconstruct HTML slide decks:

```python
from src.models.slide_deck import SlideDeck
from src.models.slide import Slide

# Parse existing HTML file
deck = SlideDeck.from_html("output/slides.html")

# Access slides
print(f"Number of slides: {len(deck)}")
first_slide = deck[0]

# Manipulate slides
deck.swap_slides(0, 1)              # Swap first two slides
deck.move_slide(from_index=5, to_index=2)  # Move slide
removed = deck.remove_slide(3)      # Remove a slide

# Add new slides
new_slide = Slide(html='<div class="slide"><h1>New Slide</h1></div>')
deck.add_slide(new_slide, position=4)

# Clone existing slide
cloned = deck[0].clone()
deck.add_slide(cloned)

# Modify CSS globally
deck.css = deck.css.replace('#EB4A34', '#00A3E0')

# Reconstruct and save
deck.save("output/modified_slides.html")

# For web APIs
deck_json = deck.to_dict()  # JSON-serializable dict
slide_html = deck.render_slide(3)  # Render individual slide
```

See [SLIDE_PARSER_DESIGN.md](SLIDE_PARSER_DESIGN.md) for detailed design and API documentation.

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
│   ├── config/           # Configuration and settings management
│   │   ├── client.py     # Singleton Databricks client
│   │   ├── settings.py   # Pydantic settings with YAML/env loading
│   │   └── loader.py     # YAML configuration loaders
│   ├── models/           # Data models
│   │   ├── slide.py      # Slide class for individual slides (✅ NEW)
│   │   └── slide_deck.py # SlideDeck class for parsing/knitting HTML (✅ NEW)
│   └── services/         # Core business logic
│       ├── agent.py      # SlideGeneratorAgent with LangChain
│       └── tools.py      # Genie tool for data queries
├── config/
│   ├── config.yaml       # Application configuration
│   ├── mlflow.yaml       # MLflow tracking and serving config
│   └── prompts.yaml      # System prompts and templates
├── tests/
│   ├── fixtures/
│   │   └── sample_slides.html  # Sample HTML for testing (✅ NEW)
│   ├── unit/             # Unit tests
│   │   ├── test_agent.py       # Agent unit tests
│   │   ├── test_slide.py       # Slide class tests (✅ NEW)
│   │   ├── test_slide_deck.py  # SlideDeck class tests (✅ NEW)
│   │   └── test_tools.py       # Tool unit tests
│   └── integration/      # Integration tests
│       ├── test_agent_integration.py      # Agent integration tests
│       ├── test_genie_integration.py      # Genie integration tests
│       └── test_slide_deck_integration.py # Slide deck integration tests (✅ NEW)
├── docs/                 # Documentation
│   ├── AGENT_IMPLEMENTATION_PLAN.md  # Agent implementation specs
│   └── IMPLEMENTATION_SUMMARY.md     # Phase 2 summary
├── pyproject.toml        # Project configuration
├── PROJECT_PLAN.md       # Detailed project plan
├── SLIDE_PARSER_DESIGN.md # Slide parser design (✅ NEW)
└── README.md             # This file
```

## Current Status

**Phase 1 - Foundation Setup**: ✅ Complete
- ✅ Project structure and folder organization
- ✅ YAML-based configuration system (`config.yaml` and `prompts.yaml`)
- ✅ Singleton Databricks client with flexible authentication
- ✅ Pydantic-based settings management with validation
- ✅ Comprehensive error handling and logging
- ✅ Pytest framework with fixtures and unit tests

**Phase 2 - LangChain Agent Implementation**: ✅ Complete
- ✅ SlideGeneratorAgent with ChatDatabricks integration
- ✅ LangChain StructuredTool for Genie queries
- ✅ AgentExecutor with multi-turn tool calling
- ✅ MLflow manual tracing with custom span attributes
- ✅ Message formatting for chat interface support
- ✅ Comprehensive unit tests (all passing)
- ✅ Integration tests with mocked responses (all passing)
- ✅ System prompt configuration in `config/prompts.yaml`
- ✅ Complete conversation history capture

**Phase 3 - Slide Parser Implementation**: ✅ Complete
- ✅ `Slide` class for wrapping individual slide HTML
- ✅ `SlideDeck` class for parsing, manipulating, and reconstructing HTML
- ✅ BeautifulSoup4 integration for robust HTML parsing
- ✅ Support for CSS, JavaScript, and metadata extraction
- ✅ Slide manipulation operations (add, remove, move, swap)
- ✅ HTML reconstruction (knitting) for full decks and individual slides
- ✅ Web API support with JSON serialization (`to_dict()`)
- ✅ Round-trip testing (parse → manipulate → save → parse)
- ✅ 64 comprehensive tests (all passing)
- ✅ Integration with existing output directory

**Next Phase**: FastAPI Integration and Frontend - see [PROJECT_PLAN.md](PROJECT_PLAN.md) for details

## Contributing

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for development guidelines and implementation steps.

## License

*License information to be added*

