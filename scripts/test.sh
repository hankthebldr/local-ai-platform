#!/bin/bash
# Test script for Local AI Platform
# Runs API tests and checks system health

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🧪 Testing Local AI Platform..."
echo ""

# Activate virtual environment
if [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "❌ Error: Virtual environment not found"
    echo "   Run ./scripts/start.sh first to set up the environment"
    exit 1
fi

# Check if API is running
echo "1. Checking API health..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://localhost:8000/health)
    echo "   ✓ API is responding"
    echo "   Status: $(echo $HEALTH | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")"
else
    echo "   ⚠️  API is not running"
    echo "   Start the API with: ./scripts/start.sh"
fi

echo ""
echo "2. Checking Ollama connection..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "   ✓ Ollama is responding"
    MODEL_COUNT=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys, json; print(len(json.load(sys.stdin)['models']))")
    echo "   Models available: $MODEL_COUNT"
else
    echo "   ❌ Ollama is not responding"
fi

echo ""
echo "3. Running unit tests..."
cd "$PROJECT_ROOT"
pytest tests/test_api.py -v --tb=short

echo ""
echo "4. Testing API endpoints..."

# Test models endpoint
echo ""
echo "   Testing /v1/models..."
MODELS_RESPONSE=$(curl -s http://localhost:8000/v1/models 2>/dev/null || echo "{}")
MODEL_COUNT=$(echo $MODELS_RESPONSE | python3 -c "import sys, json; d=json.load(sys.stdin); print(len(d.get('data', [])))" 2>/dev/null || echo "0")
if [ "$MODEL_COUNT" -gt "0" ]; then
    echo "   ✓ Models endpoint working ($MODEL_COUNT models)"
else
    echo "   ⚠️  No models found or endpoint not responding"
fi

# Test chat completion (if models available)
if [ "$MODEL_COUNT" -gt "0" ]; then
    echo ""
    echo "   Testing /v1/chat/completions..."
    FIRST_MODEL=$(echo $MODELS_RESPONSE | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || echo "mistral:7b")

    CHAT_RESPONSE=$(curl -s http://localhost:8000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\": \"$FIRST_MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Say 'test successful' and nothing else.\"}]}" \
        2>/dev/null || echo "{}")

    if echo $CHAT_RESPONSE | grep -q "choices"; then
        echo "   ✓ Chat completions endpoint working"
        RESPONSE_TEXT=$(echo $CHAT_RESPONSE | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'][:50])" 2>/dev/null || echo "")
        echo "   Response preview: $RESPONSE_TEXT..."
    else
        echo "   ⚠️  Chat completions endpoint not responding correctly"
    fi
fi

echo ""
echo "✅ Testing complete!"
