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

# Start the API server
echo ""
echo "🌐 Starting API server..."
echo "   API will be available at http://localhost:8000"
echo "   API docs at http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

cd "$PROJECT_ROOT"
python -m api.main

# Cleanup on exit
trap 'echo ""; echo "👋 Shutting down..."; [ -n "$OLLAMA_PID" ] && kill $OLLAMA_PID 2>/dev/null || true' EXIT
