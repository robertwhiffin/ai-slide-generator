# Suggested Python Project Directory Structure

## Current vs Recommended Structure

### **Recommended Structure (Python Best Practices)**

```
slide-generator/
├── README.md                          # Project overview and usage
├── pyproject.toml                     # Modern Python packaging (replaces setup.py)
├── requirements.txt                   # Production dependencies
├── requirements-dev.txt               # Development dependencies
├── .gitignore                        # Already good!
├── .env.example                      # Environment variables template
├── Makefile                          # Common development tasks
│
├── src/                              # Source code root
│   └── slide_generator/              # Main package
│       ├── __init__.py
│       ├── __main__.py               # Entry point: python -m slide_generator
│       ├── config.py                 # Configuration management
│       │
│       ├── core/                     # Core business logic
│       │   ├── __init__.py
│       │   ├── chatbot.py           # Main chatbot logic
│       │   └── chatbot_langchain.py # LangChain implementation
│       │
│       ├── tools/                    # Tool implementations
│       │   ├── __init__.py
│       │   ├── html_slides.py
│       │   └── uc_tools.py
│       │
│       ├── frontend/                 # UI components
│       │   ├── __init__.py
│       │   ├── gradio_app.py
│       │   └── templates/            # If using HTML templates
│       │
│       ├── deploy/                   # Deployment utilities
│       │   ├── __init__.py
│       │   └── deploy.py
│       │
│       └── utils/                    # Shared utilities
│           ├── __init__.py
│           ├── logging.py
│           └── exceptions.py
│
├── tests/                            # Test suite
│   ├── __init__.py
│   ├── conftest.py                   # Pytest configuration
│   ├── unit/                         # Unit tests
│   │   ├── test_chatbot.py
│   │   ├── test_html_slides.py
│   │   └── test_tools.py
│   ├── integration/                  # Integration tests
│   │   └── test_end_to_end.py
│   └── fixtures/                     # Test data
│       └── sample_slides.html
│
├── docs/                             # Documentation
│   ├── index.md
│   ├── api/                         # API documentation
│   ├── guides/                      # User guides
│   └── development.md               # Development setup
│
├── scripts/                          # Development/deployment scripts
│   ├── setup.sh                     # Environment setup
│   ├── lint.sh                      # Code quality checks
│   └── deploy.sh                    # Deployment script
│
├── docker/                           # Docker configurations
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose.dev.yml
│
├── .github/                          # GitHub workflows (if using GitHub)
│   └── workflows/
│       ├── ci.yml                   # Continuous integration
│       └── deploy.yml               # Deployment workflow
│
└── output/                           # Generated files (keep as is)
    ├── .gitkeep                     # Keep directory in git
    └── *.html                       # Generated slides (ignored by git)
```

## **Key Improvements from Current Structure**

### 1. **Source Layout (`src/` directory)**
- **Benefits**: Prevents import issues, cleaner testing, better packaging
- **Standard**: Modern Python projects use `src/` layout
- **Import**: `from slide_generator.core.chatbot import Chatbot`

### 2. **Package Naming**
- **Current**: `python/` (generic)
- **Recommended**: `slide_generator/` (descriptive)
- **Convention**: Use underscores, not hyphens in package names

### 3. **Configuration Management**
```python
# src/slide_generator/config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-claude-sonnet-4")
```

### 4. **Entry Point**
```python
# src/slide_generator/__main__.py
"""Entry point for the slide generator."""
import sys
from .frontend.gradio_app import main

if __name__ == "__main__":
    sys.exit(main())
```

### 5. **Modern Packaging (`pyproject.toml`)**
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "slide-generator"
version = "0.1.0"
description = "AI-powered slide deck generator"
authors = [{name = "Your Name", email = "your.email@example.com"}]
dependencies = [
    "gradio>=4.0.0",
    "databricks-sdk",
    "langchain-databricks",
    "langchain-core",
    "pathlib",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "black",
    "flake8",
    "mypy",
    "pre-commit",
]

[project.scripts]
slide-generator = "slide_generator.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.black]
line-length = 88
target-version = ['py39']

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

### 6. **Development Workflow**
```bash
# Makefile
.PHONY: install dev test lint format clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"
	pre-commit install

test:
	pytest tests/

lint:
	flake8 src/ tests/
	mypy src/

format:
	black src/ tests/
	isort src/ tests/

clean:
	find . -type d -name __pycache__ -delete
	find . -name "*.pyc" -delete
```

## **Migration Steps**

### **Phase 1: Restructure Source Code**
```bash
mkdir -p src/slide_generator/{core,tools,frontend,deploy,utils}
mv python/chatbot/* src/slide_generator/core/
mv python/tools/* src/slide_generator/tools/
mv python/frontend/* src/slide_generator/frontend/
mv python/deploy/* src/slide_generator/deploy/
```

### **Phase 2: Update Imports**
```python
# Before
from python.chatbot.chatbot import Chatbot
from python.tools.html_slides import HtmlDeck

# After  
from slide_generator.core.chatbot import Chatbot
from slide_generator.tools.html_slides import HtmlDeck
```

### **Phase 3: Add Configuration**
```python
# src/slide_generator/config.py
from pathlib import Path
import os

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Environment settings
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "databricks-claude-sonnet-4")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
```

## **Benefits of This Structure**

✅ **Professional**: Follows Python packaging standards  
✅ **Scalable**: Easy to add new features and modules  
✅ **Testable**: Clear separation of tests and source  
✅ **Deployable**: Proper packaging for distribution  
✅ **Maintainable**: Logical organization and clear dependencies  
✅ **CI/CD Ready**: Structure supports automated workflows  
✅ **Documentation**: Organized docs and examples  
✅ **Environment**: Clear dev/prod separation

## **Tools Integration**

### **Code Quality**
- **Black**: Code formatting
- **Flake8**: Linting  
- **MyPy**: Type checking
- **Pre-commit**: Git hooks

### **Testing**
- **Pytest**: Test framework
- **Coverage**: Code coverage
- **Tox**: Multi-environment testing

### **Documentation**
- **MkDocs**: Documentation site
- **Sphinx**: API documentation
- **README**: Project overview

This structure will make your project more professional, maintainable, and easier to collaborate on!

