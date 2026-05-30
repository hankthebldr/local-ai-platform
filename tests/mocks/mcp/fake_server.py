#!/usr/bin/env python3
"""Minimal fake stdio MCP server for testing the runner pool.

Speaks JSON-RPC line-delimited frames on stdin/stdout. Supports just
enough of the protocol to drive ``MCPRunnerPool`` tests:

  initialize                → empty result
  notifications/initialized → no response (notification)
  tools/list                → one tool named "echo"
  tools/call (name=echo)    → result echoes ``arguments``
  tools/call (name=boom)    → JSON-RPC error

Environment knobs (set on the spawned subprocess by tests via
``MCPServerConfig.env``):

  FAKE_MCP_SLEEP_AFTER_INIT_MS   — pause after handshake before reading
                                   the next request. Lets a test verify
                                   timeout handling.
  FAKE_MCP_CRASH_ON_REQUEST      — exit(1) instead of responding to the
                                   first non-init request. Lets a test
                                   verify crash detection + respawn.
  FAKE_MCP_FAIL_INIT             — exit(2) during initialize so tests
                                   can verify spawn-failure cleanup.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> int:
    if os.environ.get("FAKE_MCP_FAIL_INIT"):
        return 2

    initialized = False
    crash_on_request = bool(os.environ.get("FAKE_MCP_CRASH_ON_REQUEST"))
    sleep_after_init_ms = int(os.environ.get("FAKE_MCP_SLEEP_AFTER_INIT_MS", "0"))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "fake-mcp", "version": "0.1"},
                    },
                }
            )
            continue
        if method == "notifications/initialized":
            initialized = True
            if sleep_after_init_ms:
                time.sleep(sleep_after_init_ms / 1000.0)
            continue
        if not initialized:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": "not initialized"},
                }
            )
            continue
        if crash_on_request:
            return 1
        if method == "tools/list":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo back its arguments",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    },
                }
            )
            continue
        if method == "tools/call":
            params = msg.get("params") or {}
            tool_name = params.get("name")
            args = params.get("arguments") or {}
            if tool_name == "echo":
                _send({"jsonrpc": "2.0", "id": req_id, "result": {"echoed": args}})
            elif tool_name == "boom":
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": "boom"},
                    }
                )
            else:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"unknown tool {tool_name}",
                        },
                    }
                )
            continue
        _send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"unknown method {method}"},
            }
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
