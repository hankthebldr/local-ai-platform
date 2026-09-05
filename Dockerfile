FROM python:3.11-slim

LABEL maintainer="Local AI Platform"
LABEL description="FastAPI server for local LLM inference"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Install core + RAG dependencies (chromadb + langchain + sentence-transformers).
# requirements-rag.txt extends requirements-core.txt AND requirements-onnx.txt
# via `-r`, so installing rag gives us all three. Needed for the Documents tab
# and any embedding-backed feature (onnx is the torch-free encoder substrate).
COPY setup/requirements-core.txt setup/requirements-rag.txt setup/requirements-onnx.txt setup/
RUN pip install --no-cache-dir -r setup/requirements-rag.txt

# Copy application code + runtime data (workflows, agents, prompts, model
# registry). These directories are read at runtime — workflows.py reads YAML
# from ./workflows, AgentService scans ./agents, roles router serves
# ./prompts/roles, and inventory.py imports MODEL_REGISTRY from ./models.
COPY api/ api/
COPY models/ models/
COPY agents/ agents/
COPY workflows/ workflows/
COPY prompts/ prompts/
COPY plugins/ plugins/
# Bake the agent grounding corpus into the image. Several agent YAMLs
# (xql-data-model-engineer, xdm-schema-navigator, xql-snippet-curator,
# xql-rules-reviewer) declare context_sources of the form
# `docs/seed/xql/<file>` — without this COPY those files resolve to
# /app/docs/seed/xql/* which doesn't exist, the loader logs
# "Context file not found" warnings, and the agents run without their
# grounding knowledge (degraded XQL/XDM output). ~8.9 MB / 88 files.
COPY docs/seed/ docs/seed/

# Curated discovery seeds + operator profiles + default search settings.
# These are git-tracked repo data read at runtime from CWD-relative paths
# (WORKDIR=/app): skills.py reads data/discovery/skills_catalog.json, mcp.py
# reads data/discovery/mcp_catalog.json, inventory.py reads
# data/discovery/model_benchmarks.json, ProfileService scans data/profiles/,
# and search_service reads data/config/search_settings.json. Without these
# COPYs every container shipped with EMPTY catalogs and no profiles.
#
# Named explicitly rather than `COPY data/` on purpose: the build context's
# data/config/ also holds runtime secrets in a developer tree
# (api_keys.yaml, first-run-key.txt) which must never be baked into an image.
# .dockerignore is the second line of defence.
COPY data/discovery/ data/discovery/
COPY data/profiles/ data/profiles/
COPY data/config/search_settings.json data/config/

COPY .env.example .env

# Create data directories
RUN mkdir -p data/logs data/cache && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=3).raise_for_status()" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
