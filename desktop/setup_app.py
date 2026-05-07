"""py2app build configuration for Local AI Platform"""
from setuptools import setup

APP = ["app.py"]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Local AI Platform",
        "CFBundleDisplayName": "Local AI Platform",
        "CFBundleIdentifier": "com.localai.platform",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    },
    "packages": [
        "api", "fastapi", "uvicorn", "pydantic", "httpx",
        "rich", "yaml", "starlette", "anyio",
    ],
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
