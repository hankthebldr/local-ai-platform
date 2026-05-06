#!/bin/bash
# Start script for Local AI Platform
# Starts Ollama and the API server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 Starting Local AI Platform..."
echo ""

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Error: Ollama is not installed"
    echo "   Please install Ollama from https://ollama.ai"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    echo "⚠️  Warning: Virtual environment not found"
    echo "   Creating virtual environment..."
    python3 -m venv "$PROJECT_ROOT/venv"
    source "$PROJECT_ROOT/venv/bin/activate"
    echo "   Installing dependencies..."
    pip install -r "$PROJECT_ROOT/setup/requirements.txt"
else
    source "$PROJECT_ROOT/venv/bin/activate"
fi

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama is not running. Starting Ollama..."
    ollama serve > /tmp/ollama.log 2>&1 &
    OLLAMA_PID=$!
    echo "   Ollama started (PID: $OLLAMA_PID)"

    # Wait for Ollama to be ready
    echo "   Waiting for Ollama to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "   ✓ Ollama is ready"
            break
        fi
        sleep 1
    done
else
    echo "✓ Ollama is already running"
fi

# Check for available models
echo ""
echo "📦 Checking installed models..."
MODEL_COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys, json; print(len(json.load(sys.stdin)['models']))" 2>/dev/null || echo "0")

if [ "$MODEL_COUNT" -eq "0" ]; then
    echo "⚠️  No models installed"
    echo "   To download a model, run: ollama pull mistral:7b"
    echo "   Or use: python models/download.py mistral"
else
    echo "✓ Found $MODEL_COUNT installed model(s)"
    curl -s http://localhost:11434/api/tags | python3 -c "
import sys, json
models = json.load(sys.stdin)['models']
for model in models:
    size_gb = model['size'] / (1024**3)
    print(f\"   - {model['name']} ({size_gb:.1f} GB)\")
" 2>/dev/null || true
fi

# Create .env file if it doesn't exist
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo ""
    echo "⚠️  No .env file found. Creating from template..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo "✓ Created .env file"
fi

# Resolve the bind host the API server will use so the printed URL matches
# the real listener (API_HOST in .env can override the default 0.0.0.0).
API_HOST_RAW="$(grep -E '^[[:space:]]*API_HOST=' "$PROJECT_ROOT/.env" 2>/dev/null \
    | tail -n1 | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs)"
API_HOST_RAW="${API_HOST_RAW:-0.0.0.0}"
if [ "$API_HOST_RAW" = "0.0.0.0" ] || [ -z "$API_HOST_RAW" ]; then
    UI_HOST="localhost"
else
    UI_HOST="$API_HOST_RAW"
fi
API_PORT_RAW="$(grep -E '^[[:space:]]*API_PORT=' "$PROJECT_ROOT/.env" 2>/dev/null \
    | tail -n1 | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs)"
API_PORT_RAW="${API_PORT_RAW:-8000}"
UI_URL="http://${UI_HOST}:${API_PORT_RAW}"

# Start the API server (also serves the web dashboard at /)
echo ""
echo "🌐 Starting API + Web UI..."
echo "   Web dashboard:  ${UI_URL}/"
echo "   API docs:       ${UI_URL}/docs"
echo "   Health:         ${UI_URL}/health"
echo ""

# Best-effort: open the dashboard in the user's browser once the server
# is responding. Skipped if SKIP_BROWSER=1 or no opener is available.
if [ "${SKIP_BROWSER:-0}" != "1" ]; then
    (
        for _ in $(seq 1 30); do
            if curl -sf -m 1 "${UI_URL}/health" >/dev/null 2>&1; then
                if command -v xdg-open >/dev/null 2>&1; then
                    xdg-open "${UI_URL}/" >/dev/null 2>&1 || true
                elif command -v open >/dev/null 2>&1; then
                    open "${UI_URL}/" >/dev/null 2>&1 || true
                fi
                exit 0
            fi
            sleep 0.5
        done
    ) &
fi

echo "Press Ctrl+C to stop the server"
echo ""

cd "$PROJECT_ROOT"
python -m api.main

# Cleanup on exit
trap 'echo ""; echo "👋 Shutting down..."; [ -n "$OLLAMA_PID" ] && kill $OLLAMA_PID 2>/dev/null || true' EXIT
