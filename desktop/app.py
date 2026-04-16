#!/usr/bin/env python3
"""
Local AI Platform — macOS Desktop App

PyWebView wrapper that:
1. Starts the FastAPI server in a background thread
2. Opens a native macOS window pointing at the dashboard
3. Shows the setup wizard on first run
"""

import os
import sys
import time
import threading

import requests
import webview

# Ensure the platform code is importable
APP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

APP_DIR = os.path.expanduser("~/.local-ai-platform")
SETUP_FLAG = os.path.join(APP_DIR, "setup_complete")
HOST = "127.0.0.1"
PORT = 8000


def start_server():
    """Start the FastAPI server in a background thread."""
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


def wait_for_server(timeout=15):
    """Block until the server responds to /health."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://{HOST}:{PORT}/health", timeout=1)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            time.sleep(0.3)
    return False


def main():
    os.makedirs(APP_DIR, exist_ok=True)

    # Start server
    server = threading.Thread(target=start_server, daemon=True)
    server.start()

    if not wait_for_server():
        print("ERROR: Server failed to start within 15 seconds", file=sys.stderr)
        sys.exit(1)

    # Choose URL based on first-run state
    url = f"http://{HOST}:{PORT}"
    if not os.path.exists(SETUP_FLAG):
        url += "/setup"

    # Open native window
    webview.create_window(
        "Local AI Platform",
        url,
        width=1200,
        height=800,
        min_size=(900, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
