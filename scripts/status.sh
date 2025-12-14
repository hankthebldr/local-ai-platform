#!/bin/bash
# Status script for Local AI Platform
# Shows current system status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "📊 Local AI Platform Status"
echo "═══════════════════════════════════════"
echo ""

# Check Ollama
echo "Ollama Service:"
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  Status: ✓ Running"
    echo "  URL: http://localhost:11434"

    # List models
    MODEL_COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys, json; print(len(json.load(sys.stdin)['models']))" 2>/dev/null || echo "0")
    echo "  Models: $MODEL_COUNT installed"

    if [ "$MODEL_COUNT" -gt "0" ]; then
        echo ""
        curl -s http://localhost:11434/api/tags | python3 -c "
import sys, json
models = json.load(sys.stdin)['models']
for i, model in enumerate(models, 1):
    size_gb = model['size'] / (1024**3)
    quant = model.get('details', {}).get('quantization_level', 'N/A')
    print(f'  {i}. {model[\"name\"]:25s} {size_gb:6.1f} GB  ({quant})')
" 2>/dev/null || true
    fi
else
    echo "  Status: ✗ Not running"
    echo "  Start with: ollama serve"
fi

echo ""
echo "───────────────────────────────────────"
echo ""

# Check API
echo "API Server:"
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "  Status: ✓ Running"
    echo "  URL: http://localhost:8000"
    echo "  Docs: http://localhost:8000/docs"

    HEALTH=$(curl -s http://localhost:8000/health)
    API_STATUS=$(echo $HEALTH | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
    OLLAMA_STATUS=$(echo $HEALTH | python3 -c "import sys, json; print(json.load(sys.stdin).get('ollama_status', 'unknown'))" 2>/dev/null || echo "unknown")

    echo "  API Status: $API_STATUS"
    echo "  Ollama Connection: $OLLAMA_STATUS"
else
    echo "  Status: ✗ Not running"
    echo "  Start with: ./scripts/start.sh"
fi

echo ""
echo "───────────────────────────────────────"
echo ""

# Check environment
echo "Environment:"
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "  .env file: ✓ Present"
else
    echo "  .env file: ✗ Missing (will use defaults)"
fi

if [ -d "$PROJECT_ROOT/venv" ]; then
    echo "  Virtual env: ✓ Present"
else
    echo "  Virtual env: ✗ Missing"
fi

echo ""
echo "═══════════════════════════════════════"
