FROM python:3.11-slim

LABEL maintainer="Local AI Platform"
LABEL description="FastAPI server for local LLM inference"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Install core dependencies only
COPY setup/requirements-core.txt setup/requirements-core.txt
RUN pip install --no-cache-dir -r setup/requirements-core.txt

# Copy application code
COPY api/ api/
COPY .env.example .env

# Create data directories
RUN mkdir -p data/logs data/cache && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=3).raise_for_status()" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
