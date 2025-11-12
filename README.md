# AI Slide Generator

A full-stack web application that generates HTML slide decks using LLMs. The system provides a chat interface where users can ask natural language questions, and the AI agent queries structured data through Databricks Genie to produce professional HTML presentations with data-driven insights and visualizations.

**Current Phase**: Phase 2 Complete - Enhanced UI with drag-and-drop editing, HTML editor, debugging tools, and defensive chart rendering

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

**Phase 4 - Web Application (Phase 1 MVP)**: ✅ Complete
- ✅ FastAPI backend with chat endpoint and CORS middleware
- ✅ Pydantic request/response models for API
- ✅ ChatService wrapper with single session support
- ✅ Health check endpoint for monitoring
- ✅ React + TypeScript frontend with Vite
- ✅ Tailwind CSS for styling
- ✅ Two-panel layout (Chat 30% | Slides 70%)
- ✅ Real-time message display with role-based styling
- ✅ Collapsible tool call messages for debugging
- ✅ Iframe-based slide rendering with isolated CSS/JS
- ✅ Responsive slide scaling to fit container width
- ✅ Helper scripts (`start_app.sh`, `stop_app.sh`) for easy deployment
- ✅ Automated health checks and logging

**Phase 5 - Enhanced UI (Phase 2)**: ✅ Complete
- ✅ Drag-and-drop slide reordering with `@dnd-kit`
- ✅ HTML editor modal with Monaco editor
- ✅ Intelligent HTML validation (multi-class support)
- ✅ Slide duplication and deletion with confirmations
- ✅ Optimistic UI updates with error rollback
- ✅ Amusing loading messages at bottom of chat
- ✅ Raw HTML debugging views (rendered and text)
- ✅ Defensive chart rendering (try-catch wrapper + AI prompt)
- ✅ Interactive parser testing script
- ✅ Backend raw HTML storage for debugging
- ✅ New `/api/slides/*` endpoints for slide manipulation
- ✅ TypeScript `erasableSyntaxOnly` compatibility

**Slide Rendering:**
- Slides are generated at fixed 1280x720 dimensions for consistency
- Frontend dynamically scales slides to fit the container width (up to 1x native size)
- Adapts to all screen sizes from mobile to 4K displays

**Current Limitations:**
- Single session only (no multi-user support)
- No session persistence (state lost on restart)
- No authentication
- No undo/redo functionality
- No slide export (PDF, PowerPoint, etc.)

**What's Working:**
- ✅ Drag-and-drop slide reordering
- ✅ HTML editing with validation
- ✅ Slide duplication and deletion
- ✅ Real-time chart rendering with defensive error handling
- ✅ Raw HTML debugging views
- ✅ Responsive design (mobile to 4K)

**Next Phases**: 
- Phase 3: Databricks deployment (Apps, Unity Catalog integration)
- Phase 4: Multi-session support with persistence (SQLite/Postgres)
- Future: Export to PDF/PPTX, undo/redo, collaborative editing

## Phase 2 Features (Complete)

### Enhanced User Experience
- ✅ **Amusing Loading Messages**: Rotating funny messages at bottom of chat while the agent works (every 3 seconds)
- ✅ **Drag-and-Drop Reordering**: Click and drag slides to reorder them
- ✅ **HTML Editor**: Edit slide HTML directly with Monaco editor (VS Code experience)
- ✅ **Intelligent Validation**: Accepts multi-class divs (e.g., `class="slide title-slide"`)
- ✅ **Slide Duplication**: One-click slide copying
- ✅ **Slide Deletion**: Remove unwanted slides (with confirmation)
- ✅ **Visual Feedback**: Smooth animations and loading states
- ✅ **Optimistic Updates**: UI updates immediately with backend sync

### Debugging & Quality
- ✅ **Raw HTML Views**: Two debugging tabs to inspect AI-generated HTML
  - "Raw HTML (Rendered)": View full HTML output in iframe
  - "Raw HTML (Text)": Inspect raw HTML as plain text
- ✅ **Defensive Chart Rendering**: Belt-and-braces approach to prevent rendering errors
  - Frontend try-catch wrapper around chart scripts
  - Updated AI prompt to generate defensive JavaScript with null checks
- ✅ **Interactive Parser Test**: `test_parser_interactive.py` script for debugging HTML parsing
- ✅ **Raw HTML Storage**: Backend stores original AI output for comparison

### User Interactions

#### Reordering Slides
1. Click and hold the move icon (☰) on any slide
2. Drag to desired position
3. Drop to reorder
4. Changes save automatically to backend

#### Editing Slides
1. Click the edit icon (✏️) on any slide
2. Monaco editor opens with full HTML
3. Make changes to slide content
4. Validation ensures `<div class="slide">` wrapper exists
5. Click "Save Changes" to persist

#### Other Actions
- **Duplicate**: Click copy icon (📋) to create a duplicate after the original
- **Delete**: Click trash icon (🗑️) to delete (confirms before deleting, prevents deleting last slide)

### Technical Implementation
- **Backend**: 
  - New `/api/slides/*` endpoints for manipulation (GET, PUT, PATCH, POST, DELETE)
  - Raw HTML storage in `ChatService` for debugging
  - Enhanced `ChatResponse` model with `raw_html` field
- **Frontend**: 
  - `@dnd-kit` for smooth drag-and-drop interactions
  - `@monaco-editor/react` for VS Code-like HTML editing
  - Try-catch wrapper in `SlideTile` for defensive script execution
  - Three view modes: Tiles, Raw HTML (Rendered), Raw HTML (Text)
- **State Management**: Optimistic updates with error rollback
- **Validation**: Regex-based validation with word boundaries for multi-class support
- **AI Prompt Engineering**: Defensive JavaScript patterns for Chart.js initialization

**Debugging Tools:**
- `test_parser_interactive.py`: Interactive script for testing HTML parsing
  - Load HTML from files or generate via agent
  - Compare original vs. parsed HTML
  - Inspect CSS, scripts, and individual slides
  - Save parsed components for analysis

**Note**: Still single-session only. Multi-session support coming in Phase 4.

## Technologies

### Backend
- **Python 3.10+**: Core language for robust type support and modern features
- **LangChain**: Agent framework for tool-calling and multi-step workflows
- **databricks-langchain**: Official Databricks LangChain integration for ChatDatabricks
- **Databricks SDK**: Integration with Databricks LLM serving and Genie APIs
- **Databricks Genie**: SQL-based structured data retrieval with natural language interface
- **MLflow 3.0+**: Experiment tracking, metrics logging, and distributed tracing
- **FastAPI**: Lightweight, high-performance API framework with auto-generated docs
- **Pydantic**: Data validation and settings management for type safety
- **BeautifulSoup4**: HTML parsing for slide deck manipulation
- **lxml**: Fast HTML parser backend for BeautifulSoup
- **uvicorn**: ASGI server for FastAPI applications

### Frontend
- **React 18**: Modern UI library with hooks and concurrent features
- **TypeScript**: Type-safe JavaScript for robust frontend development
- **Vite**: Fast build tool and dev server with hot module replacement
- **Tailwind CSS**: Utility-first CSS framework for rapid UI development
- **React Icons**: Icon library for UI elements
- **@dnd-kit**: Modern drag-and-drop toolkit for React (Phase 2)
- **Monaco Editor**: VS Code's editor for HTML editing in the browser (Phase 2)

### Development Tools
- **uv**: Fast Python package manager for dependency management
- **pytest**: Testing framework for comprehensive test coverage
- **ruff**: Fast linting and formatting for code quality

### Why These Technologies?

**Backend:**
- **LangChain + ChatDatabricks**: Official agent framework with native Databricks support for tool-calling
- **Databricks LLM + Genie**: Native integration provides seamless data access and AI capabilities
- **Agent Architecture**: Modern LLM pattern with tool-calling for flexible, extensible design
- **MLflow 3.0**: Manual tracing with custom spans for complete observability
- **FastAPI**: Async support and automatic API documentation generation
- **Pydantic**: Strong typing ensures data validation and reduces runtime errors
- **BeautifulSoup4**: Robust HTML parsing that handles AI-generated slides with varying structure
- **PyYAML**: Flexible configuration management for prompts and settings

**Frontend:**
- **React + TypeScript**: Type-safe component development with modern hooks
- **Vite**: Lightning-fast HMR and optimized production builds
- **Tailwind CSS**: Rapid UI development without context switching
- **Two-Panel Layout**: Clear separation of chat and slide viewing

**Development:**
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

**Quick Start (Recommended):**

The easiest way to run both backend and frontend:

```bash
# Start both services
./start_app.sh

# Stop both services
./stop_app.sh
```

This will:
- Create virtual environment if needed
- Install all dependencies
- Start backend on port 8000
- Start frontend on port 3000
- Perform health checks

**Access the application:**
- **Web UI**: http://localhost:3000
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

**Manual Start (Alternative):**

If you prefer to run services separately:

**Backend:**
```bash
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install  # First time only
npm run dev
```

**View Logs:**
```bash
# Backend logs
tail -f logs/backend.log

# Frontend logs
tail -f logs/frontend.log
```

### Using the Web Interface

1. Open http://localhost:3000 in your browser
2. Type a message in the chat input (e.g., "Create slides about Q3 sales performance")
3. Set max slides (default: 10)
4. Press Enter or click Send
5. Watch slides appear in real-time on the right panel
6. Tool calls are collapsible in the chat for detailed inspection

### Making API Requests

You can also interact directly with the API:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Create slides about Q3 sales performance",
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
deck.insert_slide(new_slide, position=4)

# Clone existing slide
cloned = deck[0].clone()
deck.append_slide(cloned)

# Modify CSS globally
deck.css = deck.css.replace('#EB4A34', '#00A3E0')

# Reconstruct and save
deck.save("output/modified_slides.html")

# For web APIs
deck_json = deck.to_dict()  # JSON-serializable dict
slide_html = deck.render_slide(3)  # Render individual slide
```

See [SLIDE_PARSER_DESIGN.md](SLIDE_PARSER_DESIGN.md) for detailed design and API documentation.

### Debugging Tools

**Interactive Parser Test Script:**

When you encounter rendering issues or want to debug HTML parsing:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run interactive parser test
python test_parser_interactive.py
```

The script provides:
1. **Load from file**: Test parsing of existing HTML files
2. **Generate via agent**: Create new slides and test immediately
3. **Detailed analysis**: Compare original vs. parsed HTML
4. **Component inspection**: View CSS, scripts, and individual slides
5. **Save outputs**: Export parsed components for manual review

**Raw HTML Debugging Views (Web UI):**

In the slide panel, switch between view modes:
- **Tiles**: Normal slide view with manipulation controls
- **Raw HTML (Rendered)**: Full HTML output from AI in an iframe
- **Raw HTML (Text)**: Plain text view of AI-generated HTML

Use these views to:
- Verify the AI generated correct HTML
- Distinguish between AI generation issues vs. parsing issues
- Debug chart rendering problems
- Inspect CSS and JavaScript

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
│   ├── api/              # FastAPI application (✅ Phase 1 MVP)
│   │   ├── main.py       # FastAPI app initialization with CORS
│   │   ├── models/       # Pydantic request/response models
│   │   │   ├── requests.py
│   │   │   └── responses.py
│   │   ├── routes/       # API endpoints
│   │   │   └── chat.py   # Chat endpoint
│   │   └── services/     # API business logic
│   │       └── chat_service.py  # Chat service wrapper
│   ├── config/           # Configuration and settings management
│   │   ├── client.py     # Singleton Databricks client
│   │   ├── settings.py   # Pydantic settings with YAML/env loading
│   │   └── loader.py     # YAML configuration loaders
│   ├── models/           # Data models
│   │   ├── slide.py      # Slide class for individual slides
│   │   └── slide_deck.py # SlideDeck class for parsing/knitting HTML
│   └── services/         # Core business logic
│       ├── agent.py      # SlideGeneratorAgent with LangChain
│       └── tools.py      # Genie tool for data queries
├── frontend/             # React + TypeScript frontend (✅ Phase 1 MVP)
│   ├── src/
│   │   ├── components/   # React components
│   │   │   ├── ChatPanel/     # Chat interface
│   │   │   ├── SlidePanel/    # Slide display
│   │   │   └── Layout/        # App layout
│   │   ├── services/     # API client
│   │   │   └── api.ts
│   │   ├── types/        # TypeScript type definitions
│   │   │   ├── message.ts
│   │   │   └── slide.ts
│   │   ├── App.tsx       # Main app component
│   │   └── main.tsx      # Entry point
│   ├── package.json      # Frontend dependencies
│   ├── vite.config.ts    # Vite configuration
│   └── tailwind.config.js # Tailwind CSS configuration
├── config/
│   ├── config.yaml       # Application configuration
│   ├── mlflow.yaml       # MLflow tracking and serving config
│   └── prompts.yaml      # System prompts and templates
├── tests/
│   ├── fixtures/
│   │   └── sample_slides.html  # Sample HTML for testing
│   ├── unit/             # Unit tests
│   │   ├── test_agent.py
│   │   ├── test_slide.py
│   │   ├── test_slide_deck.py
│   │   └── test_tools.py
│   └── integration/      # Integration tests
│       ├── test_agent_integration.py
│       ├── test_genie_integration.py
│       └── test_slide_deck_integration.py
├── docs/                 # Documentation
│   ├── AGENT_IMPLEMENTATION_PLAN.md
│   └── IMPLEMENTATION_SUMMARY.md
├── logs/                 # Application logs (gitignored)
│   ├── backend.log
│   └── frontend.log
├── start_app.sh          # Start both backend and frontend
├── stop_app.sh           # Stop both services gracefully
├── test_parser_interactive.py  # Interactive HTML parser debugging tool (✅ Phase 2)
├── pyproject.toml        # Python project configuration
├── PROJECT_PLAN.md       # Detailed project plan
├── PHASE_1_MVP.md        # Phase 1 MVP implementation guide
├── PHASE_2_ENHANCED_UI.md # Phase 2 Enhanced UI implementation guide (✅ NEW)
├── README_PHASE1.md      # Phase 1 user documentation
├── SLIDE_PARSER_DESIGN.md # Slide parser design
└── README.md             # This file
```

See [PHASE_1_MVP.md](PHASE_1_MVP.md), [PHASE_2_ENHANCED_UI.md](PHASE_2_ENHANCED_UI.md), and [README_PHASE1.md](README_PHASE1.md) for detailed documentation.

## Contributing

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for development guidelines and implementation steps.

## License

*License information to be added*

