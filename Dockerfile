FROM python:3.11-slim

LABEL maintainer="Local AI Platform"
LABEL description="FastAPI server for local LLM inference"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Install core + RAG dependencies (chromadb + langchain + sentence-transformers).
# requirements-rag.txt extends requirements-core.txt via `-r`, so installing rag
# gives us both. Needed for the Documents tab and any embedding-backed feature.
COPY setup/requirements-core.txt setup/requirements-rag.txt setup/
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
COPY .env.example .env

# Create data directories
RUN mkdir -p data/logs data/cache && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=3).raise_for_status()" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
