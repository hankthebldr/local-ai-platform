"""
py2app build configuration for Local AI Platform

Usage:
    python desktop/setup_py2app.py py2app
"""

from setuptools import setup

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
    "packages": ["api", "plugins"],
    "plist": {
        "CFBundleName": "Local AI Platform",
        "CFBundleDisplayName": "Local AI Platform",
        "CFBundleIdentifier": "com.localai.platform",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
