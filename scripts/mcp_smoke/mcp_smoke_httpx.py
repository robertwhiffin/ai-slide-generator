"""Post-deploy smoke test for the tellr MCP endpoint.

Runs a full create_deck -> poll -> ready flow against a deployed
tellr Databricks App using a real user token. Prints each step's
outcome.

Usage:
    export TELLR_URL=https://<your-tellr-app-url>
    export DATABRICKS_TOKEN=<your-databricks-token>
    python scripts/mcp_smoke/mcp_smoke_httpx.py

Exits 0 on success, non-zero with an error message on failure.
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx


# The MCP endpoint path has a mandatory trailing slash; POST /mcp
# returns 307 -> /mcp/.
MCP_PATH_SUFFIX = "/mcp/"
# MCP Streamable HTTP requires this Accept header to support the spec
# revision the server advertises (negotiated during initialize).
ACCEPT = "application/json, text/event-stream"


def _decode_response(resp: httpx.Response) -> dict:
    """Return the JSON-RPC response body, handling both plain JSON and SSE.

    FastMCP replies with text/event-stream when the client Accept
    includes it. Extract the first `data: {...}` frame.
    """
    ctype = resp.headers.get("content-type", "").lower()
    if "event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise RuntimeError(
            f"SSE response without a data line:\n{resp.text[:500]}"
        )
    return resp.json()


def main() -> int:
    tellr_url = os.environ.get("TELLR_URL", "").rstrip("/")
    token = os.environ.get("DATABRICKS_TOKEN", "")

    if not tellr_url:
        print("ERROR: TELLR_URL is required", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: DATABRICKS_TOKEN is required", file=sys.stderr)
        return 2

    mcp_url = f"{tellr_url}{MCP_PATH_SUFFIX}"
    headers_base = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": ACCEPT,
    }

    print(f"Smoke-testing {mcp_url}")

    # Step 1: initialize
    print("Step 1: initialize")
    init_body = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "tellr-smoke", "version": "0.0.1"},
        },
    }
    resp = httpx.post(mcp_url, headers=headers_base, json=init_body, timeout=30)
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id")
    if not session_id:
        print(f"ERROR: no mcp-session-id in response headers: {dict(resp.headers)}")
        return 1
    print(f"  mcp-session-id: {session_id}")

    mcp_headers = {**headers_base, "mcp-session-id": session_id}

    # Step 1b: required notifications/initialized
    print("Step 1b: notifications/initialized")
    notif_resp = httpx.post(
        mcp_url,
        headers=mcp_headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        timeout=30,
    )
    # 200/202 are both acceptable for a notification ack.
    if notif_resp.status_code >= 300:
        print(
            f"WARNING: notifications/initialized returned HTTP {notif_resp.status_code}; "
            f"proceeding anyway"
        )

    # Step 2: tools/list
    print("Step 2: tools/list")
    resp = httpx.post(
        mcp_url,
        headers=mcp_headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        timeout=30,
    )
    resp.raise_for_status()
    body = _decode_response(resp)
    tool_names = [t["name"] for t in body["result"]["tools"]]
    print(f"  tools: {tool_names}")
    expected = {"create_deck", "get_deck_status", "edit_deck", "get_deck"}
    missing = expected - set(tool_names)
    if missing:
        print(f"ERROR: missing tools {missing}")
        return 1

    # Step 3: create_deck
    print("Step 3: create_deck")
    resp = httpx.post(
        mcp_url,
        headers=mcp_headers,
        json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "create_deck",
                "arguments": {
                    "prompt": "a three-slide smoke-test deck about the weather"
                },
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = _decode_response(resp)
    result = body.get("result", {})
    content = result.get("content") or []
    text_block = content[0] if content else {}
    payload_text = text_block.get("text", "{}") if isinstance(text_block, dict) else "{}"
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        payload = result
    if result.get("isError"):
        print(f"ERROR from create_deck: {payload_text}")
        return 1
    session_id_deck = payload["session_id"]
    request_id = payload["request_id"]
    print(
        f"  session_id={session_id_deck}, request_id={request_id}, "
        f"status={payload['status']}"
    )

    # Step 4: poll get_deck_status (up to 10 minutes)
    print("Step 4: poll get_deck_status (up to 10 minutes)")
    start = time.time()
    last_status = None
    while time.time() - start < 600:
        resp = httpx.post(
            mcp_url,
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {
                    "name": "get_deck_status",
                    "arguments": {
                        "session_id": session_id_deck,
                        "request_id": request_id,
                    },
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        body = _decode_response(resp)
        result = body.get("result", {})
        content = result.get("content") or []
        payload_text = (
            content[0].get("text", "{}") if content and isinstance(content[0], dict) else "{}"
        )
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = result

        status = payload.get("status")
        if status != last_status:
            print(f"  status={status}  (elapsed={int(time.time() - start)}s)")
            last_status = status

        if status == "ready":
            print(f"  slide_count={payload.get('slide_count')}")
            print(f"  deck_url={payload.get('deck_url')}")
            html_doc = payload.get("html_document", "")
            if not html_doc.lower().startswith("<!doctype"):
                print(f"ERROR: html_document does not start with <!doctype>")
                return 1
            print("SUCCESS")
            return 0
        if status == "failed":
            print(f"FAILED: {payload.get('error')}")
            return 1

        time.sleep(2)

    print("TIMEOUT: generation did not complete within 10 minutes")
    return 1


if __name__ == "__main__":
    sys.exit(main())
