# Multi-Turn Conversation Test Guide

Interactive test script for exploring the multi-turn slide generation capabilities.

## Quick Start

```bash
# Activate virtual environment
source .venv/bin/activate

# Run interactive test
python test_multi_turn_live.py
```

## Features

### 🔄 Multi-Turn Conversations
- Start with an initial question
- Ask follow-up questions interactively
- Agent maintains full conversation context
- Genie conversation ID persisted across turns

### 💬 Interactive Commands

| Command | Description |
|---------|-------------|
| `<your question>` | Ask a follow-up question |
| `state` | View current session state |
| `help` | Show available commands |
| `quit`, `exit`, `q` | End conversation |

### 📊 What You'll See

**For Each Turn:**
- Session ID and Genie conversation ID
- HTML output size
- Number of messages exchanged
- Tool calls made
- Response latency
- Total conversation turns

**Session State:**
- Created timestamp
- Message count
- Last interaction time
- Full conversation history
- Chat message list

**Message Flow (with `-v`):**
- 👤 User questions
- 🤖 Assistant tool calls and responses
- 🔧 Tool responses from Genie
- Full conversation trace

## Usage Examples

### Basic Interactive Mode
```bash
python test_multi_turn_live.py
```

**Example Interaction:**
```
Turn 1: "Create slides about Q3 sales"
Turn 2: "Add a comparison to Q2"
Turn 3: "Change the color scheme to blue"
Turn 4: "Make the titles more concise"
```

### Custom Initial Question
```bash
python test_multi_turn_live.py --question "Create a revenue analysis for 2024"
```

### Verbose Output (See All Details)
```bash
python test_multi_turn_live.py -v
```

### Non-Interactive Mode (Single Turn)
```bash
python test_multi_turn_live.py --auto
```

### Limit Slides
```bash
python test_multi_turn_live.py --max-slides 5
```

### Don't Save HTML Files
```bash
python test_multi_turn_live.py --no-save
```

## Example Session

```
================================================================================
  Multi-Turn Agent Test - Real LLM & Genie Integration
================================================================================

--- Step 1: Creating Agent ---

✅ Agent created successfully
  LLM Endpoint: databricks-meta-llama-3-1-405b-instruct
  Genie Space ID: 01jc123...
  MLflow Experiment: slide-generator-dev

--- Step 2: Creating Conversation Session ---

✅ Session created successfully
  Session ID: a7f3c2d1-4b5e-6789-0abc-def012345678
  Active Sessions: 1

--- Step 3: Turn 1 - Initial Request (max 10 slides) ---

Question: Create a brief overview of Q3 sales performance with 3-5 slides

🤖 Generating slides (this may take 30-60 seconds)...
✅ Slides generated successfully in 45.32 seconds

--- Turn 1 - Results Summary ---

  Session ID: a7f3c2d1...
  Genie Conversation ID: 9a8b7c6d...
  HTML Length: 12,456 characters
  New Messages: 7
  Tool Calls: 2
  Latency: 45.32 seconds
  Total Turns: 1

💾 Saved to: output/slides_turn1_20251111_091234.html

--- Session State ---

  Session ID: a7f3c2d1-4b5e-6789-0abc-def012345678
  Created At: 2025-11-11T09:12:34.567890
  Message Count: 1
  Last Interaction: 2025-11-11T09:13:19.890123
  Genie Conversation ID: 9a8b7c6d-5e4f-3210-abcd-ef0123456789
  Chat History Messages: 2

Conversation History:
  1. USER: Create a brief overview of Q3 sales performance with 3-5 slides
  2. ASSISTANT: [HTML Output]

================================================================================
  Interactive Multi-Turn Conversation
================================================================================

💬 You can now ask follow-up questions!
   Type 'quit' or 'exit' to end the conversation
   Type 'state' to view session state
   Type 'help' for more commands

--------------------------------------------------------------------------------
Turn 2:
You: Add a slide comparing Q3 to Q2

🤖 Generating response (this may take 30-60 seconds)...
✅ Response generated in 38.21 seconds

--- Turn 2 - Results Summary ---

  Session ID: a7f3c2d1...
  Genie Conversation ID: 9a8b7c6d...
  HTML Length: 14,892 characters
  New Messages: 7
  Tool Calls: 1
  Latency: 38.21 seconds
  Total Turns: 2

💾 Saved to: output/slides_turn2_20251111_091357.html

--------------------------------------------------------------------------------
Turn 3:
You: state

--- Session State ---

  Session ID: a7f3c2d1-4b5e-6789-0abc-def012345678
  Created At: 2025-11-11T09:12:34.567890
  Message Count: 2
  Last Interaction: 2025-11-11T09:13:57.123456
  Genie Conversation ID: 9a8b7c6d-5e4f-3210-abcd-ef0123456789
  Chat History Messages: 4

Conversation History:
  1. USER: Create a brief overview of Q3 sales performance with 3-5 slides
  2. ASSISTANT: [HTML Output]
  3. USER: Add a slide comparing Q3 to Q2
  4. ASSISTANT: [HTML Output]

--------------------------------------------------------------------------------
Turn 4:
You: quit

👋 Ending conversation...

--- Cleaning Up ---

✅ Session cleaned up
  Total Turns: 2

================================================================================
  Multi-Turn Test Complete ✅
================================================================================
```

## Testing Scenarios

### 1. Iterative Refinement
```
Turn 1: "Create sales slides"
Turn 2: "Add more data visualizations"
Turn 3: "Make it more executive-friendly"
Turn 4: "Add an appendix with raw data"
```

### 2. Style Changes
```
Turn 1: "Create Q3 performance slides"
Turn 2: "Change color scheme to company brand colors"
Turn 3: "Make fonts larger"
Turn 4: "Add more white space"
```

### 3. Content Additions
```
Turn 1: "Show revenue trends"
Turn 2: "Add a slide about top customers"
Turn 3: "Include a competitor comparison"
Turn 4: "Add future projections"
```

### 4. Context-Aware Queries
```
Turn 1: "Show KPMG consumption data"
Turn 2: "How does this compare to last month?"  # Agent knows "this" = KPMG
Turn 3: "What about their forecast?"            # Agent maintains context
```

## Troubleshooting

### "Session not found" Error
- Make sure you don't accidentally close/restart the agent
- Each session is tied to a single agent instance

### No Response from LLM
- Check Databricks credentials
- Verify LLM endpoint is accessible
- Check network connectivity

### Genie Errors
- Verify Genie space ID in config
- Ensure you have access to the Genie space
- Check Genie space is active

### Memory Issues with Long Conversations
- Current implementation uses ConversationBufferMemory
- Very long conversations (>20 turns) may hit token limits
- Consider starting a new session for fresh context

## Output Files

Each turn saves a separate HTML file:
```
output/
  slides_turn1_20251111_091234.html
  slides_turn2_20251111_091357.html
  slides_turn3_20251111_091542.html
  ...
```

Compare files across turns to see how the agent modifies slides based on your requests.

## Tips for Best Results

1. **Be Specific**: "Add a bar chart showing monthly revenue" vs "add more charts"
2. **Reference Context**: Agent sees previous turns, so you can say "change that slide" or "make it shorter"
3. **One Change at a Time**: Better results with focused edits than multiple simultaneous changes
4. **Check State**: Use `state` command to see conversation history and verify context
5. **Start Fresh**: If conversation goes off-track, start a new session

## Advanced Usage

### Save All HTML Files
```bash
# Files automatically saved to output/ directory
ls -lah output/slides_turn*.html
```

### View HTML Immediately
```bash
# On macOS
open output/slides_turn1_*.html

# On Linux
xdg-open output/slides_turn1_*.html
```

### Compare Across Turns
```bash
# See file sizes change
du -h output/slides_turn*.html

# Count HTML elements
grep -c "<div class=\"slide" output/slides_turn*.html
```

## What This Tests

✅ Session creation and management  
✅ Conversation history preservation  
✅ Genie conversation_id persistence  
✅ Multi-turn context awareness  
✅ Edit request handling  
✅ Tool usage with context  
✅ HTML generation across turns  
✅ Session state tracking  
✅ Error handling  

## Related Files

- `src/services/agent.py` - Agent implementation
- `CHATBOT_CONVERSION.md` - Implementation plan
- `MULTI_TURN_SUMMARY.md` - Technical summary
- `test_agent_live.py` - Single-turn test script

