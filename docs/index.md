# Slide Generator Documentation

## Overview

The Slide Generator is an AI-powered tool for creating professional slide decks using natural language. It supports both HTML and PowerPoint output formats and provides a user-friendly Gradio interface.

## Features

- **Natural Language Interface**: Create slides by describing what you want
- **Multiple Slide Types**: Title slides, agenda slides, and content slides  
- **Smart Positioning**: Title always at position 0, agenda at position 1
- **Slide Reordering**: Move slides to different positions with intelligent shifting
- **HTML Output**: Generates beautiful HTML presentations using Reveal.js
- **Gradio Interface**: Easy-to-use web interface
- **Databricks Integration**: Uses Databricks LLM endpoints
- **LangChain Support**: Optional LangChain integration for enhanced functionality

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/slide-generator.git
cd slide-generator

# Install in development mode
make dev

# Or install directly
pip install -e ".[dev,langchain]"
```

### Basic Usage

```bash
# Run with Gradio interface
slide-generator

# Or use Python module
python -m slide_generator

# Run in debug mode
slide-generator --debug

# Specify custom host/port
slide-generator --host 0.0.0.0 --port 8080
```

### Environment Setup

Copy the environment template and configure:

```bash
cp .env.example .env
```

Required environment variables:
- `DATABRICKS_HOST`: Your Databricks workspace URL
- `DATABRICKS_TOKEN`: Your Databricks access token
- `LLM_ENDPOINT`: Name of your LLM serving endpoint

## Architecture

The project follows a clean architecture with clear separation of concerns:

```
src/slide_generator/
├── core/           # Business logic (chatbot)
├── tools/          # Slide generation tools
├── frontend/       # UI interfaces
├── deploy/         # Deployment utilities
├── utils/          # Shared utilities
└── config.py       # Configuration management
```

## API Reference

### Creating Slides Programmatically

```python
from slide_generator import Chatbot, HtmlDeck
from databricks.sdk import WorkspaceClient

# Initialize components
deck = HtmlDeck()
ws = WorkspaceClient()
chatbot = Chatbot(deck, "your-endpoint", ws)

# Create slides
conversation = [
    {"role": "system", "content": "You are a slide assistant"},
    {"role": "user", "content": "Create a deck about Python"}
]

response, stop = chatbot.call_llm(conversation)
```

### Available Tools

1. **tool_add_title_slide**: Add/replace title slide at position 0
2. **tool_add_agenda_slide**: Add/replace agenda slide at position 1  
3. **tool_add_content_slide**: Add content slide (appends)
4. **tool_reorder_slide**: Move slide from one position to another
5. **tool_get_html**: Get current HTML of the deck
6. **tool_write_html**: Save deck to file

## Development

### Setup Development Environment

```bash
# Install development dependencies
make dev

# Run tests
make test

# Run with coverage
make test-cov

# Format code
make format

# Run linting
make lint

# Run all checks
make check
```

### Project Structure

The project follows Python packaging best practices:

- **src/ layout**: Prevents import issues and enables proper testing
- **pyproject.toml**: Modern Python packaging configuration
- **Comprehensive testing**: Unit and integration tests
- **Code quality tools**: Black, flake8, mypy, pre-commit
- **Documentation**: MkDocs-based documentation

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting: `make check`  
5. Submit a pull request

## Deployment

### Docker Deployment

```bash
# Build container
docker build -t slide-generator .

# Run container
docker run -p 7860:7860 slide-generator
```

### Production Deployment

```bash
# Build package
make build

# Deploy to PyPI
make publish
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | false | Enable debug mode |
| `LOG_LEVEL` | INFO | Logging level |
| `LLM_ENDPOINT` | databricks-claude-sonnet-4 | LLM endpoint name |
| `GRADIO_HOST` | 127.0.0.1 | Gradio server host |
| `GRADIO_PORT` | 7860 | Gradio server port |
| `GRADIO_SHARE` | false | Enable public sharing |
| `MAX_SLIDES_PER_DECK` | 50 | Maximum slides per deck |

### Custom Themes

You can customize slide themes by modifying the `SlideTheme` class:

```python
from slide_generator.tools.html_slides import SlideTheme

custom_theme = SlideTheme(
    background_rgb=(240, 240, 240),
    title_color_rgb=(50, 50, 50),
    title_font_size_px=48
)

deck = HtmlDeck(theme=custom_theme)
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Make sure you installed in development mode with `pip install -e .`
2. **LLM Connection Errors**: Verify your Databricks credentials and endpoint name
3. **Permission Errors**: Check that the output directory is writable

### Getting Help

- Check the [GitHub Issues](https://github.com/your-username/slide-generator/issues)
- Review the API documentation
- Run with `--debug` flag for verbose logging

## License

This project is licensed under the MIT License. See the LICENSE file for details.


