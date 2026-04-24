#!/usr/bin/env python3
"""
Setup Router — First-run wizard endpoints
"""

import os
import shutil
import subprocess
import json

import requests as http_requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path

from ..logging_config import logger

router = APIRouter(tags=["setup"])

APP_DIR = os.path.expanduser("~/.enclave")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
STATIC_DIR = Path(__file__).parent.parent / "static"


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
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"status": "started"}

    logger.info("Installing Ollama via CLI installer...")
    try:
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Ollama install failed: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"Install failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Install timed out after 120s")

    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                stream=True, timeout=1800,
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
