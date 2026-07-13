#!/usr/bin/env python3
"""
Setup Router — First-run wizard endpoints
"""

import os
import shutil
import subprocess
import json
import ipaddress

import requests as http_requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path

from ..logging_config import logger

router = APIRouter(tags=["setup"])

APP_DIR = os.path.expanduser("~/.enclave")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
STATIC_DIR = Path(__file__).parent.parent / "static"

# Hosts considered "local" for the auto-license-delivery endpoint. Docker
# Compose puts the browser behind a bridge so client.host shows up as an
# RFC1918 address (172.16.0.0/12 typically). Anything outside loopback or
# RFC1918 gets a 403 — that's where remote license activation will
# eventually replace the local-key handoff.
_LOCAL_CLIENT_HOSTS = {"localhost"}

# GP-2 (P0-14): a request that traversed a reverse proxy carries a forwarding
# header, and request.client.host is then the PROXY's address (often loopback
# or a bridge IP) — NOT the real remote client. We cannot trust the peer
# address to prove locality in that case, so the presence of ANY of these is a
# hard refusal: the operator's first-run master key must never be handed to a
# client we can't prove is on the box.
_FORWARDING_HEADERS = ("X-Forwarded-For", "Forwarded", "X-Real-IP")


def _is_local_client(request: Request) -> bool:
    # Proxied request → the peer address is the proxy, not the client. Refuse.
    for h in _FORWARDING_HEADERS:
        if request.headers.get(h):
            return False
    if not request.client:
        return False
    host = request.client.host or ""
    # The literal "localhost" is not parseable as an IP but is loopback by
    # name (some ASGI servers report it verbatim).
    if host in _LOCAL_CLIENT_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    # Loopback (127.0.0.0/8, ::1) or RFC1918 private (incl. the Docker-bridge
    # parity path 172.16.0.0/12). is_private correctly EXCLUDES public ranges
    # like 172.5.x that a naive "172." prefix check wrongly trusted.
    return ip.is_loopback or ip.is_private


@router.get("/api/setup/local-license")
async def local_license(request: Request) -> dict:
    """
    Return the local first-run / "license" key so the SPA can auto-sign-in
    on first boot. Localhost / private-network clients only.

    The key delivered here is the same master key written to
    ``data/config/first-run-key.txt`` at first boot. It exists today as the
    only credential; in the future, paid-product activation will replace
    this with a real license-server roundtrip and this endpoint will gate
    on entitlement.
    """
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Local clients only")

    key_path = Path(os.getenv("DATA_CONFIG_DIR", "data/config")) / "first-run-key.txt"
    if not key_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No first-run key on disk; auth may be disabled or the "
            "keystore was provisioned externally.",
        )
    try:
        key = key_path.read_text().strip()
    except OSError as exc:
        logger.warning("Failed to read first-run-key.txt: %s", exc)
        raise HTTPException(status_code=500, detail="Could not read license key")
    if not key:
        raise HTTPException(status_code=500, detail="License key file is empty")
    return {
        "key": key,
        "kind": "local-first-run",
        "source": "data/config/first-run-key.txt",
    }


@router.get("/setup")
async def setup_page():
    setup_html = STATIC_DIR / "setup.html"
    if setup_html.exists():
        return FileResponse(setup_html, media_type="text/html")
    raise HTTPException(status_code=404, detail="Setup page not found")


@router.get("/api/setup/check-ollama")
async def check_ollama():
    ollama_path = shutil.which("ollama")
    installed = ollama_path is not None
    running = False
    try:
        r = http_requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        running = r.status_code == 200
    except Exception:
        pass
    return {"installed": installed, "running": running, "path": ollama_path}


@router.post("/api/setup/install-ollama")
async def install_ollama():
    if shutil.which("ollama"):
        try:
            http_requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
            return {"status": "already_running"}
        except Exception:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"status": "started"}

    logger.info("Installing Ollama via CLI installer...")
    try:
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Ollama install failed: {result.stderr}")
            raise HTTPException(
                status_code=500, detail=f"Install failed: {result.stderr[:200]}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Install timed out after 120s")

    subprocess.Popen(
        ["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    logger.info("Ollama installed and started")
    return {"status": "installed"}


@router.post("/api/setup/pull-model")
async def pull_model(body: dict):
    model_name = body.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="model is required")

    def stream_pull():
        try:
            r = http_requests.post(
                f"{OLLAMA_HOST}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=1800,
            )
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    data = json.loads(line)
                    yield f"data: {json.dumps(data)}\n\n"
            yield 'data: {"status": "success"}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"status": "error", "error": str(e)})}\n\n'

    return StreamingResponse(stream_pull(), media_type="text/event-stream")


@router.post("/api/setup/complete")
async def complete_setup():
    os.makedirs(APP_DIR, exist_ok=True)
    flag_path = os.path.join(APP_DIR, "setup_complete")
    Path(flag_path).touch()
    logger.info(f"Setup complete — flag written to {flag_path}")
    return {"status": "complete"}
