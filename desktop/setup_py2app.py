"""
py2app build configuration for Enclave

Usage:
    cd <project_root>
    python desktop/setup_py2app.py py2app
"""

import sys
import os

# Ensure project root is on sys.path so py2app can find local packages
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from setuptools import setup, find_packages

APP = ["desktop/app.py"]

OPTIONS = {
    "argv_emulation": False,
    "includes": [
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pydantic",
        "yaml",
        "requests",
        "webview",
        "dotenv",
        "psutil",
    ],
    "packages": find_packages(where=PROJECT_ROOT, include=["api", "api.*"]),
    "excludes": [
        # Exclude heavy ML dependencies not needed for the desktop app
        "torch",
        "transformers",
        "accelerate",
        "bitsandbytes",
        "optimum",
        "peft",
        "trl",
        "datasets",
        "chromadb",
        "langchain",
        "langchain_community",
        "sentence_transformers",
        "llama_cpp",
        "numpy",
        "scipy",
        "matplotlib",
        "pandas",
        "PIL",
        "Pillow",
        "black",
        "blib2to3",
        "tokenizers",
        "safetensors",
        "huggingface_hub",
        "tqdm",
        "pytest",
    ],
    "resources": [
        "api/static",
        "plugins",
        ".env.example",
    ],
    "plist": {
        "CFBundleName": "Enclave",
        "CFBundleDisplayName": "Enclave",
        "CFBundleIdentifier": "com.ohno.enclave",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
