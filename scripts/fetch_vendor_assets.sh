#!/usr/bin/env bash
# Fetch web assets into api/static/vendor/ so the UI renders offline.
# Run once per release; output is committed to the repo.
#
# Fulfills README's "no internet required" promise by removing runtime
# fetches from fonts.googleapis.com and cdnjs.cloudflare.com.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/api/static/vendor"
FONTS="$VENDOR/fonts"
mkdir -p "$FONTS"

# Chrome UA triggers WOFF2 responses from Google Fonts.
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

fetch_family() {
  local family_query="$1"   # e.g. "Space+Grotesk:wght@300;400;500;600;700"
  local prefix="$2"         # e.g. "space-grotesk"
  echo "→ Fetching $prefix..."
  local css
  css=$(curl -fsSL -A "$UA" "https://fonts.googleapis.com/css2?family=${family_query}&display=swap")
  FONTS="$FONTS" PREFIX="$prefix" CSS="$css" python3 <<'PY'
import os, re, hashlib, urllib.request, pathlib
fonts_dir = pathlib.Path(os.environ["FONTS"])
prefix = os.environ["PREFIX"]
css = os.environ["CSS"]

out_blocks = []
url_count = 0
for block in re.finditer(r"@font-face\s*\{[^}]+\}", css):
    b = block.group(0)
    weight = re.search(r"font-weight:\s*(\d+)", b)
    src = re.search(r"src:\s*url\(([^)]+)\)\s*format\('([^']+)'\)", b)
    if not (weight and src):
        continue
    w = weight.group(1)
    url = src.group(1).strip()
    fmt = src.group(2).strip()
    ext = "woff2" if fmt == "woff2" else "ttf"
    # Disambiguate multi-range blocks by hashing the URL.
    tag = hashlib.sha1(url.encode()).hexdigest()[:6]
    local_name = f"{prefix}-{w}-{tag}.{ext}"
    out_path = fonts_dir / local_name
    if not out_path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(out_path, "wb") as f:
            f.write(r.read())
    url_count += 1
    rewritten = re.sub(
        r"src:\s*url\([^)]+\)\s*format\('[^']+'\)",
        f"src: url('{local_name}') format('{fmt}')",
        b,
    )
    out_blocks.append(rewritten)

css_out = "\n".join(out_blocks) + "\n"
(fonts_dir / f"{prefix}.css").write_text(css_out, encoding="utf-8")
print(f"  · {prefix}: {url_count} font files")
PY
}

fetch_family "Space+Grotesk:wght@300;400;500;600;700" "space-grotesk"
fetch_family "JetBrains+Mono:wght@300;400;500;600;700" "jetbrains-mono"

# Combined stylesheet referenced by index.html / setup.html
cat "$FONTS/space-grotesk.css" "$FONTS/jetbrains-mono.css" > "$FONTS/fonts.css"

echo "→ Fetching d3 v7 (minified)..."
curl -fsSL -o "$VENDOR/d3.v7.min.js" \
  "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"

echo "→ Fetching Drawflow 0.0.59 (no-code workflow composer)..."
curl -fsSL -o "$VENDOR/drawflow.min.css" \
  "https://cdn.jsdelivr.net/gh/jerosoler/Drawflow@0.0.59/dist/drawflow.min.css"
curl -fsSL -o "$VENDOR/drawflow.min.js" \
  "https://cdn.jsdelivr.net/gh/jerosoler/Drawflow@0.0.59/dist/drawflow.min.js"

echo "→ Fetching Dagre 0.8.5 (auto-layout for the composer)..."
curl -fsSL -o "$VENDOR/dagre.min.js" \
  "https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"

echo "→ Fetching js-yaml 4.1.0 (YAML import/export)..."
curl -fsSL -o "$VENDOR/js-yaml.min.js" \
  "https://cdnjs.cloudflare.com/ajax/libs/js-yaml/4.1.0/js-yaml.min.js"

echo ""
echo "✓ Vendor assets fetched to $VENDOR"
echo "  fonts:    $(ls "$FONTS"/*.woff2 "$FONTS"/*.ttf 2>/dev/null | wc -l | tr -d ' ')"
echo "  d3:       $(stat -f%z "$VENDOR/d3.v7.min.js") bytes"
echo "  drawflow: $(stat -f%z "$VENDOR/drawflow.min.js") JS + $(stat -f%z "$VENDOR/drawflow.min.css") CSS"
echo "  dagre:    $(stat -f%z "$VENDOR/dagre.min.js") bytes"
echo "  js-yaml:  $(stat -f%z "$VENDOR/js-yaml.min.js") bytes"
