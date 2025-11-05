# Deployment Scripts

This directory contains scripts for model registration, deployment, testing, and rollback operations for the AI Slide Generator.

## Prerequisites

- Databricks workspace access
- Environment variables configured:
  - `DATABRICKS_HOST`: Your Databricks workspace URL
  - `DATABRICKS_TOKEN`: Your personal access token
- Unity Catalog access for model registry
- Python environment with all dependencies installed

## Scripts

### 1. `register_model.py`

Register and deploy the slide generator model to Databricks Model Serving.

```bash
# Deploy to dev environment
python scripts/register_model.py --environment dev

# Deploy to production (with approval)
python scripts/register_model.py --environment prod --approve
```

**What it does:**
- Packages the agent as an MLflow PyFunc model
- Registers model in Unity Catalog
- Deploys to serving endpoint
- Configures scaling and workload settings

**Environments:**
- `dev`: Uses `slide-generator-dev` endpoint with Small workload, scale-to-zero enabled
- `prod`: Uses `slide-generator` endpoint with Medium workload, min 1 instance

### 2. `test_endpoint.py`

Test a deployed serving endpoint with sample questions.

```bash
# Test with default questions
python scripts/test_endpoint.py --endpoint slide-generator-dev

# Test with custom questions file
python scripts/test_endpoint.py --endpoint slide-generator --questions tests.json

# Test single question
python scripts/test_endpoint.py --endpoint slide-generator-dev --question "What were Q4 sales?"
```

**What it does:**
- Sends test requests to the serving endpoint
- Measures response time and success rate
- Displays trace URLs for debugging
- Provides test summary with pass/fail counts

**Custom Questions File Format (JSON):**
```json
[
  {
    "question": "What were our Q4 2023 sales?",
    "max_slides": 8
  },
  {
    "question": "Show customer trends",
    "max_slides": 10,
    "genie_space_id": "optional-space-id"
  }
]
```

### 3. `rollback_model.py`

Rollback a serving endpoint to a previous model version.

```bash
# List available versions
python scripts/rollback_model.py --list-versions main.ml_models.slide_generator_dev

# Rollback with confirmation prompt
python scripts/rollback_model.py --endpoint slide-generator-dev --version 2

# Rollback without confirmation (auto-approve)
python scripts/rollback_model.py --endpoint slide-generator --version 5 --confirm
```

**What it does:**
- Shows current endpoint configuration
- Prompts for confirmation (unless `--confirm` flag used)
- Updates endpoint to specified model version
- Waits for endpoint to be ready

## Typical Workflow

### Development Cycle

```bash
# 1. Make code changes
# 2. Test locally
pytest tests/unit/ -v

# 3. Register and deploy to dev
python scripts/register_model.py --environment dev

# 4. Test dev endpoint
python scripts/test_endpoint.py --endpoint slide-generator-dev

# 5. If tests pass, deploy to prod (with approval)
python scripts/register_model.py --environment prod --approve
```

### Rollback Procedure

```bash
# If production deployment has issues:

# 1. List available versions
python scripts/rollback_model.py --list-versions main.ml_models.slide_generator

# 2. Rollback to last known good version
python scripts/rollback_model.py --endpoint slide-generator --version 3

# 3. Verify endpoint is working
python scripts/test_endpoint.py --endpoint slide-generator
```

## Model Registry Structure

```
Unity Catalog:
├── main (catalog)
│   └── ml_models (schema)
│       ├── slide_generator_dev     (dev model)
│       │   ├── Version 1
│       │   ├── Version 2
│       │   └── ...
│       └── slide_generator         (prod model)
│           ├── Version 1
│           ├── Version 2
│           └── ...
```

## Serving Endpoints

### Development Endpoint
- **Name:** `slide-generator-dev`
- **Workload:** Small
- **Scale to Zero:** Enabled
- **Min/Max Scale:** 0-3 instances
- **Purpose:** Testing and development

### Production Endpoint
- **Name:** `slide-generator`
- **Workload:** Medium
- **Scale to Zero:** Disabled
- **Min/Max Scale:** 1-5 instances
- **Purpose:** Production workloads

## Environment Variables

Required environment variables:

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-personal-access-token"
```

Optional overrides:

```bash
export API_PORT=8000
export LOG_LEVEL=INFO
export ENVIRONMENT=development
```

## Troubleshooting

### Script Fails with "Model not found"

**Solution:** Ensure Unity Catalog model name is correct in `config/mlflow.yaml`:

```yaml
registry:
  model_name: "main.ml_models.slide_generator"
  dev_model_name: "main.ml_models.slide_generator_dev"
```

### Endpoint Creation Fails

**Possible causes:**
- Insufficient permissions in Databricks workspace
- Model not registered in Unity Catalog
- Endpoint name already exists

**Solution:** Check Databricks workspace permissions and verify model registration.

### Test Endpoint Timeouts

**Possible causes:**
- Cold start (first request to scaled-to-zero endpoint)
- Large slide generation taking > 180s
- Genie query timeout

**Solution:**
- Wait for endpoint warm-up (30-60 seconds)
- Reduce max_slides for faster generation
- Check Genie space configuration

### Rollback Fails

**Possible cause:** Target version doesn't exist or is in wrong stage

**Solution:**
```bash
# List available versions first
python scripts/rollback_model.py --list-versions <model_name>

# Verify version exists and is in Production/Staging stage
```

## Monitoring

After deployment, monitor your endpoints:

**Databricks UI:**
- Navigate to **Machine Learning** → **Serving**
- Select your endpoint
- View metrics, logs, and traces

**MLflow UI:**
- Navigate to **Machine Learning** → **Experiments**
- Find experiment: `/Users/<username>/ai-slide-generator`
- View runs, traces, and metrics

**Trace URLs:**
Each generation includes a trace URL in the response metadata:
```python
{
  "html": "...",
  "metadata": {
    "trace_url": "https://workspace.databricks.com/#mlflow/..."
  }
}
```

## Security Best Practices

1. **Never commit tokens:** Use environment variables only
2. **Rotate tokens regularly:** Update `DATABRICKS_TOKEN` periodically
3. **Use service principals:** For production deployments, use service principal tokens
4. **Limit permissions:** Grant minimum required permissions for model deployment
5. **Audit deployments:** Review all production deployments before approval

## Additional Resources

- [Databricks Model Serving Documentation](https://docs.databricks.com/machine-learning/model-serving/)
- [MLflow Models Documentation](https://mlflow.org/docs/latest/models.html)
- [Unity Catalog Model Registry](https://docs.databricks.com/machine-learning/manage-model-lifecycle/)

