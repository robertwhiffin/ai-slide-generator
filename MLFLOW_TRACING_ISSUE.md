# MLflow Tracing Investigation - Not Working from UI

**Date:** 2025-11-12  
**Status:** 🔴 Issue Identified - No Code Changes Made Yet  
**Impact:** No traces or runs being logged to MLflow when calling from the UI

---

## Problem Statement

MLflow tracing is not working for API calls from the UI. No error messages appear in logs, and no events are tracked in MLflow experiments.

## Root Cause Analysis

### 🔴 Primary Issue: Missing MLflow Run Context

**Location:** `src/services/agent.py:415`

The code uses `mlflow.start_span()` without an active MLflow run:

```python
# Current code (BROKEN):
def generate_slides(...):
    try:
        # Use mlflow.start_span for manual tracing
        with mlflow.start_span(name="generate_slides") as span:
            span.set_attribute("question", question)
            span.set_attribute("session_id", session_id)
            # ... rest of code
```

**Why this fails:**
- `mlflow.start_span()` requires an **active MLflow run** to exist first
- Without a parent run, spans are **silently ignored** (no error, no trace)
- The code was likely written for batch/script usage where `mlflow.start_run()` would be called externally
- When integrated into FastAPI web service, no run context is ever created

---

## Evidence Collected

### 1. No MLflow Logs in Backend

**File:** `logs/backend.log`

**Search performed:** Searched for:
- "MLflow"
- "mlflow"  
- "tracing"
- "experiment"

**Result:** **0 matches found**

**Expected logs that are missing:**
```python
# From agent.py:117-124
logger.info(
    "MLflow configured",
    extra={
        "tracking_uri": self.settings.mlflow.tracking_uri,
        "experiment_name": self.settings.mlflow.experiment_name,
        "experiment_id": self.experiment_id,
    },
)
```

**What this means:**
- Either `_setup_mlflow()` succeeded but logs aren't being captured (unlikely - other logs work fine)
- OR the method failed and was caught by the silent exception handler (more likely)

### 2. Silent Exception Handling

**Location:** `src/services/agent.py:104-128`

```python
def _setup_mlflow(self) -> None:
    """Configure MLflow tracking and experiment."""
    try:
        mlflow.set_tracking_uri(self.settings.mlflow.tracking_uri)
        experiment = mlflow.get_experiment_by_name(self.settings.mlflow.experiment_name)
        if experiment is None:
            self.experiment_id = mlflow.create_experiment(self.settings.mlflow.experiment_name).experiment_id
            logger.info("Created new MLflow experiment", ...)
        else:
            self.experiment_id = experiment.experiment_id
            logger.info("MLflow experiment already exists", ...)
        mlflow.set_experiment(experiment_id=self.experiment_id)
        
        logger.info("MLflow configured", ...)
    except Exception as e:
        logger.warning(f"Failed to configure MLflow: {e}")
        # Continue without MLflow if it fails
        pass  # ⚠️ PROBLEM: Silently continues without MLflow
```

**Issues:**
- Exception is caught and logged as a warning, but execution continues
- No indication to the user that MLflow is disabled
- No re-raise, so the error is suppressed

### 3. Agent Initialization Logs Missing

**Expected in logs:**
- "Initializing SlideGeneratorAgent" (line 84)
- Either "MLflow configured" OR "Failed to configure MLflow"
- "Created single session" (from ChatService)

**Actually in logs:**
- Only sees LangChain AgentExecutor output (the colored chain output)
- No agent initialization logs at all

**Implication:** Logging configuration may not be capturing module-level loggers correctly, OR logs are being written somewhere else.

### 4. Tracing Configuration Exists But Not Activated

**File:** `config/mlflow.yaml`

```yaml
tracing:
  enabled: true
  backend: "databricks"
  sample_rate: 1.0
  capture_input_output: true
  capture_model_config: true
  max_trace_depth: 10
```

**File:** `src/config/settings.py:141-157`

```python
class MLFlowTracingSettings(BaseSettings):
    """MLFlow tracing configuration."""
    enabled: bool = True
    backend: str = "databricks"
    sample_rate: float = 1.0
    capture_input_output: bool = True
    capture_model_config: bool = True
    max_trace_depth: int = 10
```

**Problem:** Configuration is loaded correctly, but **no code actually enables MLflow tracing**.

**Missing code:** No call to any of these:
- `mlflow.langchain.autolog()` - Auto-instrument LangChain
- `mlflow.enable_tracing()` - Enable tracing globally
- `mlflow.start_run()` - Create run context for spans

### 5. Code Structure Suggests Batch Usage Pattern

**Pattern observed:**
```python
# Designed for:
with mlflow.start_run(run_name="my_run"):
    agent = SlideGeneratorAgent()  # Sets up MLflow
    result = agent.generate_slides(...)  # Uses spans within run

# But actually used as:
agent = SlideGeneratorAgent()  # No run context
result = agent.generate_slides(...)  # Spans are silently ignored
```

**FastAPI Service Pattern (current):**
- Agent is created once at startup (`ChatService.__init__`)
- Same agent instance is reused for all requests
- No run context is created per request
- Spans fail silently

---

## What's Working

### ✅ Configuration Loading
- `config/mlflow.yaml` is valid and loads correctly
- Settings are properly parsed into Pydantic models
- `MLFlowSettings`, `MLFlowTracingSettings` are populated

### ✅ Databricks Authentication
- No authentication errors in logs
- Other Databricks SDK operations work (Genie queries)
- Suggests `DATABRICKS_HOST` and `DATABRICKS_TOKEN` are correct

### ✅ Agent Execution
- Agent successfully generates slides
- Tool calls (Genie queries) work correctly
- HTML output is generated and parsed
- Chat interface receives responses

---

## MLflow Configuration Details

**Experiment Path:**
```yaml
experiment_name: "/Workspace/Users/robert.whiffin@databricks.com/ai-slide-generator"
```

**Tracking URI:**
```yaml
tracking_uri: "databricks"
```

**Tracing Settings:**
- Enabled: `true`
- Backend: `databricks`
- Sample Rate: `1.0` (100% of requests)
- Capture Input/Output: `true`

---

## Solution Options

### Option 1: Wrap Each Request in MLflow Run (Recommended)

**Changes needed in `src/services/agent.py`:**

```python
def generate_slides(
    self,
    question: str,
    session_id: str,
    max_slides: int = 10,
    genie_space_id: str | None = None,
) -> dict[str, Any]:
    start_time = datetime.utcnow()
    session = self.get_session(session_id)
    
    # CREATE RUN CONTEXT
    with mlflow.start_run(
        run_name=f"slide_generation_{session_id}",
        experiment_id=self.experiment_id,
    ) as run:
        # Log run parameters
        mlflow.log_params({
            "max_slides": max_slides,
            "session_id": session_id,
            "message_count": session["message_count"],
        })
        
        # Now spans will work
        with mlflow.start_span(name="generate_slides") as span:
            span.set_attribute("question", question)
            # ... existing code ...
```

**Pros:**
- Fine-grained control over what's logged
- Each request gets its own run
- Can log custom metrics and parameters
- Explicit and clear

**Cons:**
- Requires wrapping every call site
- More code changes
- Manual instrumentation

### Option 2: Enable LangChain Autologging

**Changes needed in `src/services/agent.py`:**

```python
def _setup_mlflow(self) -> None:
    """Configure MLflow tracking and experiment."""
    try:
        mlflow.set_tracking_uri(self.settings.mlflow.tracking_uri)
        experiment = mlflow.get_experiment_by_name(self.settings.mlflow.experiment_name)
        if experiment is None:
            self.experiment_id = mlflow.create_experiment(self.settings.mlflow.experiment_name).experiment_id
        else:
            self.experiment_id = experiment.experiment_id
        mlflow.set_experiment(experiment_id=self.experiment_id)
        
        # ENABLE LANGCHAIN AUTOLOGGING
        if self.settings.mlflow.tracing.enabled:
            mlflow.langchain.autolog()
            logger.info("MLflow LangChain autologging enabled")
        
        logger.info("MLflow configured", ...)
    except Exception as e:
        logger.error(f"Failed to configure MLflow: {e}")
        raise  # Don't silently continue
```

**Pros:**
- Automatic instrumentation
- Less code to write
- Captures all LangChain operations automatically

**Cons:**
- Less control over what's logged
- May capture too much or too little
- Behavior depends on MLflow version

### Option 3: Hybrid Approach (Recommended)

**Combine both approaches:**

1. Enable autologging in `_setup_mlflow()`
2. Wrap `generate_slides()` in a run for custom metrics
3. Keep manual spans for key operations

**Changes needed:**

```python
# In _setup_mlflow():
if self.settings.mlflow.tracing.enabled:
    mlflow.langchain.autolog()

# In generate_slides():
with mlflow.start_run(run_name=f"slide_gen_{session_id}"):
    mlflow.log_params({"max_slides": max_slides})
    
    with mlflow.start_span(name="generate_slides") as span:
        # ... existing code ...
    
    mlflow.log_metrics({
        "latency_seconds": latency,
        "tool_calls": len(intermediate_steps),
    })
```

**Pros:**
- Best of both worlds
- Automatic LangChain tracing + custom metrics
- Most complete observability

**Cons:**
- More complex
- Need to ensure autolog and manual logging don't conflict

---

## Additional Issues Found

### Issue: Silent Exception Handler

**Location:** `src/services/agent.py:125-128`

```python
except Exception as e:
    logger.warning(f"Failed to configure MLflow: {e}")
    # Continue without MLflow if it fails
    pass
```

**Problem:**
- Exceptions are suppressed
- Agent continues without MLflow silently
- No indication to user that tracing is disabled

**Recommendation:**
- Change to `logger.error()` instead of `logger.warning()`
- Consider raising exception for critical failures
- Add status indicator (e.g., `self.mlflow_enabled = True/False`)

### Issue: No Logging Configuration Visible

**Observation:**
- Expected logs from agent initialization not appearing
- Other logs (from LangChain, Uvicorn) work fine
- Suggests module-level loggers may not be configured

**Files to check:**
- Look for `logging.basicConfig()` or logging configuration
- Check if uvicorn is filtering logs
- Verify log level is set to INFO or DEBUG

---

## Testing Plan

### Before Fix:
1. ✅ Confirmed no traces in MLflow UI
2. ✅ Confirmed no logs mentioning MLflow in `logs/backend.log`
3. ✅ Confirmed agent works but no observability

### After Fix:
1. ⬜ Verify MLflow experiment appears in Databricks workspace
2. ⬜ Verify runs are created for each request
3. ⬜ Verify spans appear within runs
4. ⬜ Verify parameters and metrics are logged
5. ⬜ Verify trace URLs are accessible
6. ⬜ Test failure scenario (invalid experiment name)

---

## Related Files

**Key files involved:**
- `src/services/agent.py` - Agent implementation with span creation
- `src/api/services/chat_service.py` - Service that calls agent
- `src/config/settings.py` - MLflow settings definition
- `config/mlflow.yaml` - MLflow configuration
- `src/config/loader.py` - Config loading logic

**Unused but related:**
- `src/models/mlflow_wrapper.py` - MLflow PyFunc wrapper (for Model Serving, not used yet)
- `scripts/register_model.py` - Model registration script (imports mlflow_wrapper)

---

## References

- [MLflow Tracing Documentation](https://mlflow.org/docs/latest/tracking.html#automatic-logging)
- [MLflow LangChain Integration](https://mlflow.org/docs/latest/llms/langchain/index.html)
- [Databricks MLflow Guide](https://docs.databricks.com/mlflow/index.html)

---

## Next Steps

1. **Decide on solution approach** (Option 1, 2, or 3)
2. **Implement code changes** in `src/services/agent.py`
3. **Test locally** to verify traces appear
4. **Check Databricks MLflow UI** for runs and traces
5. **Update documentation** with MLflow usage examples
6. **Consider adding health check** for MLflow connectivity

---

## Status

- [x] Issue identified
- [x] Root cause determined
- [x] Evidence collected
- [x] Solutions proposed
- [ ] Code changes implemented
- [ ] Testing completed
- [ ] Documentation updated

