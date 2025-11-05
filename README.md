# AI Slide Generator

AI-powered slide generation using Databricks.

## Technologies

- **Python 3.9+**: Core language
- **Databricks SDK**: For Databricks platform integration
- **uv**: Fast Python package manager

## Getting Started

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Activate virtual environment:**
   ```bash
   source .venv/bin/activate
   ```

3. **Configure Databricks authentication:**
   Set up your Databricks credentials using one of these methods:
   - Environment variables: `DATABRICKS_HOST`, `DATABRICKS_TOKEN`
   - Databricks CLI configuration: `~/.databrickscfg`
   - Azure CLI for Azure Databricks

## Development

### Install dev dependencies:
```bash
uv sync --extra dev
```

### Run tests:
```bash
pytest
```

### Format and lint:
```bash
ruff check .
ruff format .
```

## Project Structure

```
.
├── pyproject.toml      # Project configuration and dependencies
├── src/                # Source code
└── tests/              # Test suite
```

