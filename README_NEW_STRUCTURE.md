# Slide Generator - New Project Structure

🎉 **Welcome to the restructured Slide Generator!** 

This is a **complete copy** of your original project, reorganized following Python best practices. Your original files in the `python/` directory are **completely untouched** and continue to work as before.

## 🚀 Quick Start with New Structure

### Installation
```bash
# Install the new structure
pip install -e .

# Or with all dependencies
pip install -e ".[dev,langchain]"
```

### Run the Application
```bash
# Using the new CLI entry point
slide-generator

# Or using Python module
python -m slide_generator

# With custom options
slide-generator --host 0.0.0.0 --port 8080 --debug
```

## 📁 New vs Old Structure

| Old Location | New Location | Notes |
|--------------|-------------|-------|
| `python/chatbot/` | `src/slide_generator/core/` | Core business logic |
| `python/tools/` | `src/slide_generator/tools/` | Slide generation tools |
| `python/frontend/` | `src/slide_generator/frontend/` | Gradio interface (renamed to `gradio_app.py`) |
| `python/deploy/` | `src/slide_generator/deploy/` | Deployment utilities |
| N/A | `src/slide_generator/config.py` | **NEW**: Centralized configuration |
| N/A | `tests/` | **NEW**: Comprehensive test suite |
| N/A | `docs/` | **NEW**: Documentation |

## 🔄 Import Changes

### Before (Old Structure)
```python
from python.chatbot.chatbot import Chatbot
from python.tools.html_slides import HtmlDeck
import python.frontend.gradio_frontend as frontend
```

### After (New Structure)  
```python
from slide_generator.core.chatbot import Chatbot
from slide_generator.tools.html_slides import HtmlDeck
from slide_generator.frontend.gradio_app import main
```

## ⚡ New Features

### 1. **Configuration Management**
```python
from slide_generator.config import config

print(f"LLM Endpoint: {config.llm_endpoint}")
print(f"Output Directory: {config.output_dir}")
```

### 2. **CLI Interface**
```bash
slide-generator --help
slide-generator --mode gradio --port 8080
slide-generator --debug
```

### 3. **Proper Package Structure**
```python
# Install and import as a package
import slide_generator
from slide_generator import Chatbot, HtmlDeck
```

### 4. **Environment Configuration**
Create a `.env` file:
```bash
LLM_ENDPOINT=databricks-claude-sonnet-4
DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-token
GRADIO_PORT=7860
DEBUG=false
```

## 🧪 Testing

The new structure includes comprehensive tests:

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test types
pytest tests/unit/           # Unit tests
pytest tests/integration/    # Integration tests
pytest -m "not slow"        # Skip slow tests
```

## 🛠️ Development Workflow

```bash
# Install development dependencies
make dev

# Format code
make format

# Run linting
make lint

# Run all quality checks
make check

# Clean build artifacts
make clean
```

## 📊 Benefits of New Structure

### ✅ **Professional Standards**
- Follows Python packaging conventions
- Proper `src/` layout prevents import issues
- Modern `pyproject.toml` configuration

### ✅ **Development Experience**
- Comprehensive test suite with fixtures
- Code quality tools (black, flake8, mypy)
- Pre-commit hooks for consistency
- Development Makefile for common tasks

### ✅ **Deployment Ready**
- Pip installable package
- CLI entry points
- Docker support
- Environment-based configuration

### ✅ **Maintainable**
- Clear separation of concerns
- Centralized configuration
- Proper error handling
- Comprehensive documentation

## 🔧 Migration Guide

### Option 1: Gradual Migration
Keep using your old structure while testing the new one:

```python
# Keep using old imports for now
from python.chatbot.chatbot import Chatbot

# Test new structure in parallel
from slide_generator.core.chatbot import Chatbot as NewChatbot
```

### Option 2: Full Migration
Switch to the new structure entirely:

1. Update your import statements
2. Use the new CLI: `slide-generator` 
3. Configure with environment variables
4. Run tests: `make test`

## 📋 Available Commands

```bash
# Package management
make install          # Install package
make dev             # Development setup

# Code quality
make format          # Format code
make lint            # Run linting
make check           # All quality checks

# Testing
make test            # Run tests
make test-cov        # Tests with coverage

# Application
make run             # Run Gradio interface
make run-debug       # Run in debug mode

# Documentation
make docs            # Build documentation
make docs-serve      # Serve docs locally

# Build and publish
make build           # Build package
make clean           # Clean artifacts
```

## 🎯 What's Preserved

- **All original functionality** works exactly the same
- **Same chatbot behavior** and API
- **Same slide generation** capabilities  
- **Same Gradio interface** (just better organized)
- **Your existing files** are completely untouched

## 🎨 What's Enhanced

- **Better error handling** and logging
- **Configuration management** with environment variables
- **Professional CLI** with help and options
- **Comprehensive testing** with fixtures and mocks
- **Development tools** for code quality
- **Documentation** and examples
- **Packaging** for easy distribution

---

## 🚀 Ready to Try?

```bash
# Quick test of the new structure
pip install -e .
slide-generator --help
python -m slide_generator
```

Your original `python/` directory continues to work as before - this is a **complete copy** with improvements, not a replacement!

**Questions?** Check the documentation in `docs/` or the comprehensive test examples in `tests/`.



