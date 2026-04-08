#!/usr/bin/env python3
"""Local AI Platform — macOS Desktop App"""

import os
import socket
import subprocess
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

APP_NAME = "Local AI Platform"
OLLAMA_PORT = 11434
_ollama_proc = None


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def is_port_open(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def ensure_ollama() -> bool:
    global _ollama_proc
    if is_port_open(OLLAMA_PORT):
        return True
    for candidate in ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"]:
        if os.path.isfile(candidate):
            _ollama_proc = subprocess.Popen(
                [candidate, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(20):
                if is_port_open(OLLAMA_PORT):
                    return True
                time.sleep(0.5)
            return False
    return False


def start_server(port: int):
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=port, log_level="warning")


def cleanup():
    global _ollama_proc
    if _ollama_proc and _ollama_proc.poll() is None:
        _ollama_proc.terminate()
        try:
            _ollama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ollama_proc.kill()


def main():
    import webview

    print(f"Starting {APP_NAME}...")
    ollama_ok = ensure_ollama()
    print(f"  Ollama: {'connected' if ollama_ok else 'not found (inference disabled)'}")

    port = find_free_port()
    print(f"  API server: http://127.0.0.1:{port}")

    server = threading.Thread(target=start_server, args=(port,), daemon=True)
    server.start()

    for _ in range(40):
        if is_port_open(port):
            break
        time.sleep(0.25)
    else:
        print("ERROR: Server failed to start")
        cleanup()
        sys.exit(1)

    print(f"  Opening native window...")
    window = webview.create_window(
        APP_NAME,
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(800, 600),
    )
    webview.start()
    cleanup()


if __name__ == "__main__":
    main()
