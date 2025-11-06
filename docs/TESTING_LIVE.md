# Live Testing Guide

This guide shows how to test the agent with **real LLM and Genie calls** (no mocks).

## Quick Start

### Simple Test (Recommended)

```bash
python test_agent_simple.py
```

**What it does:**
- Creates agent with real connections
- Asks: "What data is available? Show me a sample."
- Generates 3 slides
- Saves HTML to `output/slides_TIMESTAMP.html`
- Prints basic stats

**Expected output:**
```
🚀 Creating agent...
✅ Agent ready (endpoint: databricks-claude-sonnet-4-5)

📊 Generating slides...
✅ Done!
   - HTML: 12,345 chars
   - Messages: 6
   - Tool calls: 2
   - Time: 15.3s

📄 Saved: output/slides_20251105_143022.html
   Open with: open output/slides_20251105_143022.html
```

### Detailed Test

```bash
python test_agent_live.py
```

**What it shows:**
- ✅ Agent creation with config details
- ✅ Complete conversation flow (user → assistant → tools)
- ✅ Tool calls and responses
- ✅ HTML analysis (tags, structure)
- ✅ Execution timing
- ✅ Saved output location

## Custom Questions

### Simple Test

Edit `test_agent_simple.py` and change the question:

```python
result = agent.generate_slides(
    question="Your custom question here",
    max_slides=5
)
```

### Detailed Test

Use command-line arguments:

```bash
# Custom question
python test_agent_live.py --question "Show me sales data for Q4 2023"

# More slides
python test_agent_live.py --max-slides 10

# Verbose output (shows full tool responses)
python test_agent_live.py --verbose

# Don't save HTML file
python test_agent_live.py --no-save

# Combine options
python test_agent_live.py \
    --question "Analyze customer churn trends" \
    --max-slides 8 \
    --verbose
```

## What Gets Tested

These scripts test the **complete end-to-end flow** with no mocks:

1. ✅ **Configuration Loading**
   - Loads `config/config.yaml`
   - Loads `config/prompts.yaml`
   - Loads MLflow settings

2. ✅ **Databricks Connection**
   - Uses real credentials (profile or env vars)
   - Verifies connection to workspace

3. ✅ **Agent Initialization**
   - Creates ChatDatabricks model
   - Registers Genie tool
   - Sets up prompt template
   - Creates AgentExecutor

4. ✅ **MLflow Tracing**
   - Starts span for generation
   - Logs attributes and metrics
   - Creates traces in Databricks

5. ✅ **LLM Invocation**
   - Calls real LLM endpoint
   - Gets actual responses
   - No mocked responses

6. ✅ **Tool Calling**
   - Calls real Genie space
   - Executes SQL queries
   - Returns actual data

7. ✅ **Multi-Turn Conversation**
   - LLM decides when to use tools
   - Makes multiple Genie calls if needed
   - Maintains conversation context

8. ✅ **HTML Generation**
   - LLM generates actual HTML
   - No templated output
   - Complete slide deck

9. ✅ **Message Capture**
   - All intermediate steps captured
   - Chat interface format
   - Tool calls and responses

## Prerequisites

### 1. Databricks Credentials

**Option A: Profile (Recommended)**

In `config/config.yaml`:
```yaml
databricks:
  profile: "your-profile-name"
```

**Option B: Environment Variables**

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-token"
```

### 2. Genie Space

In `config/config.yaml`:
```yaml
genie:
  default_space_id: "your-actual-genie-space-id"
```

Find your Genie space ID:
1. Go to Databricks workspace
2. Navigate to Genie
3. Open your space
4. Copy ID from URL: `.../genie/rooms/{space_id}`

### 3. LLM Endpoint

In `config/config.yaml`:
```yaml
llm:
  endpoint: "databricks-claude-sonnet-4-5"  # or your endpoint
```

## Troubleshooting

### Error: "No module named 'src'"

Make sure you're in the project root:
```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python test_agent_simple.py
```

### Error: "Failed to initialize Databricks client"

Check credentials:
```bash
# Test connection
python -c "from databricks.sdk import WorkspaceClient; w = WorkspaceClient(); print(w.current_user.me().user_name)"
```

### Error: "System prompt not found in configuration"

Verify `config/prompts.yaml` exists:
```bash
ls -la config/prompts.yaml
```

### Error: "Failed to query Genie space"

1. Check Genie space ID in `config/config.yaml`
2. Verify you have access to the space
3. Test Genie directly in the UI

### LLM Times Out

Increase timeout in `config/config.yaml`:
```yaml
llm:
  timeout: 180  # 3 minutes
```

### HTML Output is Empty or Invalid

Check:
1. System prompt in `config/prompts.yaml`
2. LLM endpoint supports tool calling
3. Genie returned valid data
4. Run with `--verbose` to see full conversation

## Example Output

### Simple Test Output

```
🚀 Creating agent...
INFO:src.services.agent:Initializing SlideGeneratorAgent
INFO:src.services.agent:MLflow configured
INFO:src.services.agent:ChatDatabricks model created
INFO:src.services.agent:Tools created
INFO:src.services.agent:Prompt template created
INFO:src.services.agent:Agent executor created
INFO:src.services.agent:SlideGeneratorAgent initialized successfully
✅ Agent ready (endpoint: databricks-claude-sonnet-4-5)

📊 Generating slides...
INFO:src.services.agent:Starting slide generation
INFO:src.services.agent:Slide generation completed
✅ Done!
   - HTML: 8,432 chars
   - Messages: 6
   - Tool calls: 1
   - Time: 12.8s

📄 Saved: output/slides_20251105_143530.html
   Open with: open output/slides_20251105_143530.html
```

### Detailed Test Output

```
================================================================================
  Live Agent Test - Real LLM & Genie Integration
================================================================================

--- Step 1: Creating Agent ---

✅ Agent created successfully
  LLM Endpoint: databricks-claude-sonnet-4-5
  Genie Space ID: 01effebcc2781b6bbb749077a55d31e3
  MLflow Experiment: /Users/robert.whiffin/ai-slide-generator

--- Step 2: Generating Slides (max 5) ---

Question: What data is available? Show me a sample.

Calling LLM and Genie (this may take 30-60 seconds)...
✅ Slides generated successfully in 14.23 seconds

--- Step 3: Results Summary ---

  HTML Length: 9,247 characters
  Total Messages: 6
  Tool Calls: 1
  Latency: 14.23 seconds

--- Step 4: Conversation Flow ---

1. 👤 USER:
   What data is available? Show me a sample.
2. 🤖 ASSISTANT (calling tool):
   Tool: query_genie_space
3. 🔧 TOOL RESPONSE:
   Data retrieved successfully:

   [{"date":"2023-01-01","sales":15000,"region":"US"},{"date":"2023-01-02","sales":18500,"region":"US"}]

   Conversation ID: conv-abc123
4. 🤖 ASSISTANT (final response):
   [HTML output - 9247 chars]

--- Step 5: HTML Preview ---

✅ Valid HTML detected
  Slide divs found: 5
  H1 headers: 5
  H2 headers: 0
  Tables: 1

--- Step 6: Saving Output ---

✅ HTML saved to: output/slides_20251105_143544.html

Open in browser:
   open output/slides_20251105_143544.html

================================================================================
  Test Complete ✅
================================================================================
Total execution time: 14.23 seconds
Tool calls made: 1
Messages exchanged: 6

📄 View your slides: open output/slides_20251105_143544.html
```

## Verifying MLflow Traces

After running tests, verify traces in Databricks:

1. Go to Databricks workspace
2. Navigate to **Machine Learning** → **Experiments**
3. Find: `/Users/<your-username>/ai-slide-generator`
4. Click on latest run
5. View **Traces** tab

**Expected trace attributes:**
- `question`: Your question
- `max_slides`: Number requested
- `model_endpoint`: LLM endpoint used
- `status`: "success"
- `output_length`: HTML character count
- `tool_calls`: Number of Genie calls
- `latency_seconds`: Execution time

## Next Steps

After verifying the agent works:

1. **Adjust prompts** in `config/prompts.yaml` to improve output
2. **Try different questions** to test various scenarios
3. **Check HTML quality** - open generated files in browser
4. **Review MLflow traces** to optimize performance
5. **Integrate into API** once confident it works

## Comparison: Mock vs Live Testing

| Aspect | Unit/Integration Tests | Live Tests |
|--------|----------------------|------------|
| **Speed** | Fast (< 1s) | Slow (10-60s) |
| **Cost** | Free | Uses LLM tokens |
| **Network** | Not needed | Required |
| **Purpose** | Verify code logic | Verify real behavior |
| **Run** | On every commit | Before deployment |
| **Mocks** | Heavy | None |

**Best practice:** Use both!
- Run mock tests frequently during development
- Run live tests before deploying or when changing prompts

## Files

- `test_agent_simple.py` - Quick test, minimal output
- `test_agent_live.py` - Detailed test with analysis
- `output/` - Generated HTML files saved here

