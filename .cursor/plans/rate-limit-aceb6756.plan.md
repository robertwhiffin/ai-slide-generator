<!-- aceb6756-055a-4cbf-9b84-249302c369c5 0fe4684d-db23-4662-9347-006b354da30c -->
# Increase LLM Timeout to Debug Rate Limiting

## Quick Test

Increase the LLM timeout from 120 to 180 seconds to determine if timeout is the cause of "Agent stopped due to max iterations" when hitting rate limits.

## Changes

In [`src/core/settings_db.py`](src/core/settings_db.py):

- Line 42: Change `timeout: int = 120` to `timeout: int = 180`
- Line 309: Change `timeout=120,` to `timeout=180,`

## After Testing

If this resolves the issue, the root cause is confirmed as timeout. We can then decide whether to:

1. Keep the higher timeout
2. Implement proper rate limit detection and retry (original plan)
3. Both

### To-dos

- [ ] Add RateLimitError exception class to agent.py
- [ ] Add retry configuration constants to SlideGeneratorAgent class
- [ ] Implement _is_rate_limit_output() detection method (checks output string)
- [ ] Implement _invoke_with_retry() with exponential backoff
- [ ] Update generate_slides() to use retry wrapper and return retry metadata
- [ ] Add rate limit fields to ChatMetadata in responses.py