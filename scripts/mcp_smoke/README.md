# MCP Smoke Tests

Manual verification scripts for the tellr MCP endpoint after deploy.
These are NOT run in CI — they require a live deployed tellr app and
a real Databricks user token.

## `mcp_smoke_httpx.py`

Runs the full `initialize → notifications/initialized → tools/list →
create_deck → poll → ready` flow using raw `httpx`. Prints each
step's outcome and exits 0 on success.

### Running

```bash
export TELLR_URL=https://<your-tellr-app-url>
export DATABRICKS_TOKEN=<a-databricks-user-token>
python scripts/mcp_smoke/mcp_smoke_httpx.py
```

Expected output ends with:

```
Step 4: poll get_deck_status (up to 10 minutes)
  status=running  (elapsed=2s)
  status=ready  (elapsed=47s)
  slide_count=3
  deck_url=https://<your-tellr-app-url>/sessions/<id>/edit
SUCCESS
```

### Notes

- The script polls every 2 seconds with a 10-minute hard timeout that
  matches the server-side `JOB_HARD_TIMEOUT_SECONDS`.
- The MCP endpoint path has a mandatory trailing slash. The script
  uses `/mcp/` directly to avoid the 307 redirect that `POST /mcp`
  returns.
- FastMCP responds with `text/event-stream` for some requests. The
  script's `_decode_response` helper handles both JSON and SSE frames.
- If `initialize` returns no `mcp-session-id` header, the deployment
  did not pick up the MCP router — redeploy and check `/api/health`.
- If auth fails with the token, try generating a fresh PAT or using
  `databricks auth login` output.
