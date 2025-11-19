# Phase 4 Setup Guide

## Quick Start: Database-Backed Configuration

This guide walks through setting up the database-backed configuration system for the first time.

## Prerequisites

- PostgreSQL database running
- Alembic migrations from Phase 1 applied
- `DATABASE_URL` environment variable set

## Step-by-Step Setup

### 1. Set Database URL

```bash
export DATABASE_URL='postgresql://localhost:5432/ai_slide_generator'
```

Or add to `.env`:
```
DATABASE_URL=postgresql://localhost:5432/ai_slide_generator
```

### 2. Run Database Migrations (if not done)

```bash
# From project root
alembic upgrade head
```

This creates the configuration tables:
- `config_profiles`
- `config_ai_infra`
- `config_genie_spaces`
- `config_mlflow`
- `config_prompts`
- `config_history`

### 3. Initialize Default Profile

```bash
python -m src.config.init_default_profile
```

This script:
- Reads configuration from `config/config.yaml` and `config/prompts.yaml`
- Creates a "default" profile in the database
- Marks it as the default profile
- Outputs success confirmation

**Expected Output:**
```
Initializing default configuration profile...
Database: localhost:5432/ai_slide_generator

✓ Default profile initialized successfully
  Profile ID: 1
  Profile Name: default
  LLM Endpoint: databricks-meta-llama-3-1-70b-instruct
  Genie Space: Default Genie Space
  MLflow Experiment: /Users/yourname/slide-generator-experiments

You can now start the application with database-backed configuration.
```

### 4. Start the Application

```bash
./start_app.sh
```

The application now:
- Loads configuration from database (not YAML)
- Uses the default profile
- Supports hot-reload without restart

### 5. Verify Configuration

```bash
# Check current configuration
curl http://localhost:8000/api/config/profiles/default

# Test hot-reload
curl -X POST http://localhost:8000/api/config/profiles/reload
```

## Using Multiple Profiles

### Create a New Profile

```bash
curl -X POST http://localhost:8000/api/config/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production",
    "description": "Production configuration",
    "copy_from_profile_id": 1
  }'
```

### Switch to New Profile

```bash
# Load profile ID 2
curl -X POST http://localhost:8000/api/config/profiles/2/load
```

### Update Configuration

```bash
# Update LLM settings for profile 2
curl -X PUT http://localhost:8000/api/config/ai-infra/2 \
  -H "Content-Type: application/json" \
  -d '{
    "llm_endpoint": "databricks-meta-llama-3-1-405b-instruct",
    "llm_temperature": 0.5
  }'

# Reload to apply changes
curl -X POST http://localhost:8000/api/config/profiles/reload?profile_id=2
```

## Hot-Reload Workflow

1. **Make Changes** via API:
   ```bash
   curl -X PUT http://localhost:8000/api/config/ai-infra/1 \
     -H "Content-Type: application/json" \
     -d '{"llm_temperature": 0.8}'
   ```

2. **Reload Configuration** (no restart needed):
   ```bash
   curl -X POST http://localhost:8000/api/config/profiles/reload
   ```

3. **Verify Changes** applied:
   ```bash
   curl http://localhost:8000/api/config/ai-infra/1
   ```

Active conversations are preserved during reload!

## Troubleshooting

### "No default profile found"

Run the initialization script:
```bash
python -m src.config.init_default_profile
```

### "DATABASE_URL not set"

Export or add to `.env`:
```bash
export DATABASE_URL='postgresql://localhost:5432/ai_slide_generator'
```

### "Reload failed"

Check logs for errors:
```bash
tail -f logs/backend.log
```

The agent remains in the previous state if reload fails.

### Agent still using old settings

Ensure you called the reload endpoint after making changes:
```bash
curl -X POST http://localhost:8000/api/config/profiles/reload
```

## Migration from YAML (Existing Deployments)

If you have an existing deployment using YAML:

1. **Backup current YAML files**
   ```bash
   cp -r config/ config.backup/
   ```

2. **Run migrations**
   ```bash
   alembic upgrade head
   ```

3. **Initialize from YAML**
   ```bash
   python -m src.config.init_default_profile
   ```

4. **Restart application**
   ```bash
   ./stop_app.sh
   ./start_app.sh
   ```

5. **Verify configuration loaded**
   ```bash
   curl http://localhost:8000/api/config/profiles/default
   ```

YAML files are no longer used at runtime but remain as defaults.

## API Reference

### Configuration Endpoints

- `GET /api/config/profiles` - List all profiles
- `GET /api/config/profiles/default` - Get default profile
- `GET /api/config/profiles/{id}` - Get specific profile
- `POST /api/config/profiles` - Create profile
- `POST /api/config/profiles/{id}/load` - Load and reload with profile
- `POST /api/config/profiles/reload` - Reload current configuration
- `PUT /api/config/ai-infra/{profile_id}` - Update LLM settings
- `PUT /api/config/genie/{profile_id}` - Manage Genie spaces
- `PUT /api/config/mlflow/{profile_id}` - Update MLflow settings
- `PUT /api/config/prompts/{profile_id}` - Update prompts

### Interactive API Documentation

Visit http://localhost:8000/docs for Swagger UI.

## Next Steps

- **Phase 5**: Frontend profile management UI
- **Phase 6**: Configuration forms for each domain
- **Phase 7**: History viewer and audit trail
- **Phase 8**: Complete deployment

## Support

For issues or questions:
- Check logs: `logs/backend.log`
- Review docs: `docs/backend-database-implementation/`
- Run tests: `pytest tests/unit/test_settings_db.py -v`

