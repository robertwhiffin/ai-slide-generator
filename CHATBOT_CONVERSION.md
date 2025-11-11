# Multi-Turn Slide Generation Analysis

## Current State
`SlideGeneratorAgent` is a **single-turn** agent that:
- Takes one question input
- Returns complete HTML slide deck with intermediate steps
- No conversation memory between invocations
- Cannot handle follow-up requests or iterative refinement

## Target Workflow
1. User asks for slides → Agent generates HTML slides (shows all tool calls)
2. User requests edits → Agent modifies existing slides with context
3. User asks for new slides → Agent creates additional slides with full context
4. **Keep all current functionality**: HTML output, tool use, intermediate steps

## Required Changes

### 1. **Add Conversation Memory**
- Track full conversation history (all messages, tool calls, outputs)
- Include previous HTML outputs in context for edits
- Persist per-session state across multiple `generate_slides()` calls

### 2. **Session Management**
- Add `session_id` parameter to `generate_slides()`
- Store per-session data:
  - Chat history (messages)
  - Previous HTML outputs
  - Genie conversation_id for continuity
  - Session metadata
- Implement session storage (in-memory dict for now)
- Add methods: `create_session()`, `get_session()`, `clear_session()`

### 3. **Update Prompt Template**
Add chat history placeholder:
```python
("system", system_prompt),
("placeholder", "{chat_history}"),  # NEW - conversation context
("human", "{input}"),
("placeholder", "{agent_scratchpad}"),
```

### 4. **Modify Agent Executor**
Add ConversationBufferMemory (stores complete conversation history):
```python
from langchain.memory import ConversationBufferMemory

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=self.tools,
    memory=memory,  # NEW
    return_intermediate_steps=True,
    ...
)
```

**Why ConversationBufferMemory:**
- Preserves exact HTML outputs for precise editing
- No information loss from summarization
- Simple implementation with no extra LLM calls
- Sufficient for typical 3-10 turn workflows
- Agent can reference exact previous messages/outputs

### 5. **Update Method Signature**
```python
def generate_slides(
    self,
    question: str,
    session_id: str,  # NEW - required for multi-turn
    max_slides: int = 10,
    genie_space_id: str | None = None,
) -> dict[str, Any]:
```

### 6. **Enhanced Return Structure**
Keep existing structure, add session tracking:
```python
{
    "html": str,              # KEEP - HTML slide deck
    "messages": list,         # KEEP - Chat messages with tool calls
    "metadata": dict,         # KEEP - Latency, tokens, etc.
    "session_id": str,        # NEW - Session identifier
    "genie_conversation_id": str,  # NEW - For Genie continuity
}
```

### 7. **Update System Prompt**
Modify prompt to handle:
- Editing existing slides (reference previous output)
- Adding new slides to existing deck
- Understanding context from conversation history
- Maintaining consistent styling across edits

### 8. **Session Storage Implementation**
```python
class SlideGeneratorAgent:
    def __init__(self):
        ...
        self.sessions: dict[str, dict] = {}  # In-memory storage
    
    def create_session(self) -> str:
        """Create new session, return ID"""
        
    def get_session(self, session_id: str) -> dict:
        """Retrieve session state"""
        
    def _store_session_state(self, session_id: str, data: dict):
        """Store conversation state"""
```

### 9. **Genie Conversation Continuity**
- Extract and store `conversation_id` from Genie responses
- Pass stored `conversation_id` in follow-up tool calls
- Maintains Genie's context across the session

### 10. **Format Messages with Context**
Update `_format_messages_for_chat()` to:
- Include previous conversation turns
- Reference previous HTML outputs when editing
- Show full conversation flow in UI

## What Stays the Same

✅ HTML slide output format  
✅ Tool usage (Genie queries)  
✅ Intermediate steps capture  
✅ MLflow tracing  
✅ Message formatting for chat UI  
✅ Error handling  
✅ Core agent logic  

## Key Differences Summary

| Aspect | Current | Multi-Turn |
|--------|---------|------------|
| Interaction | Single-turn | Multi-turn |
| State | Stateless | Stateful (sessions) |
| Output | HTML slides | HTML slides ✓ |
| Memory | None | Chat history + previous outputs |
| Context | None | Full conversation context |
| Editing | Not supported | Iterative refinement |

## Implementation Priority

1. **Session storage** (critical) - Track state across calls
2. **Memory integration** (critical) - Add LangChain memory to executor
3. **Prompt template update** (critical) - Add chat_history placeholder
4. **Method signature** (critical) - Add session_id parameter
5. **Genie continuity** (important) - Persist conversation_id per session
6. **System prompt update** (important) - Handle edit requests
7. **Session methods** (nice-to-have) - create/get/clear helpers

## Example Usage

```python
agent = create_agent()

# Initial request
result1 = agent.generate_slides(
    question="Create slides about Q3 sales",
    session_id="session_123"
)
# Returns HTML slides

# Follow-up edit
result2 = agent.generate_slides(
    question="Add a slide comparing to Q2",
    session_id="session_123"  # Same session
)
# Agent has context, modifies existing slides

# Another follow-up
result3 = agent.generate_slides(
    question="Change the color scheme to blue",
    session_id="session_123"
)
# Agent edits with full context
```

