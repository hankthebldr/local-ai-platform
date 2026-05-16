#!/bin/bash
# Enclave v1.1.1 — demo recorder orchestrator.
#
# Produces dist/demo/enclave-v1.1.1-demo.mp4 — a silent, timing-accurate walkthrough
# suitable for adding voice-over in post.
#
# Segments:
#   1. Composer canvas + Agents palette  (Playwright, browser)
#   2. OOTB xdm-rule-from-log workflow   (Playwright, browser)
#   3. Documents drop-zone + RAG         (Playwright, browser)
#   4. Mac DMG first-run / dashboard     (ffmpeg avfoundation, native)
#
# Requires:
#   - Running stack at http://127.0.0.1:8000 (auth off for clean visuals)
#   - Playwright Chromium installed (`playwright install chromium`)
#   - ffmpeg with libx264 + avfoundation input device (default on macOS Homebrew build)
#   - The built .app at dist/Enclave.app for segment 4
#
# Usage:
#   ./scripts/record_demo.sh                    # all 4 segments
#   SKIP_NATIVE=1 ./scripts/record_demo.sh      # browser-only
#   ./scripts/record_demo.sh --concat-only      # just stitch existing seg*.mp4

set -euo pipefail

cd "$(dirname "$0")/.."

OUT=dist/demo
mkdir -p "$OUT"

VPY="../../../venv/bin/python"
[ -x "$VPY" ] || VPY="./venv/bin/python"

if [ "${1:-}" != "--concat-only" ]; then
    # ── 1-3: Browser segments via Playwright ──────────────────────────────
    echo "=== [1/4] Playwright segments (composer / OOTB / documents) ==="
    "$VPY" scripts/record_demo.py
    echo

    # ── Convert each Playwright .webm to .mp4 at 30fps with x264 ──────────
    echo "=== [2/4] webm → mp4 (libx264) ==="
    n=1
    for d in "$OUT"/seg1_composer "$OUT"/seg2_ootb "$OUT"/seg3_documents; do
        webm="$(ls -t "$d"/*.webm 2>/dev/null | head -1)"
        if [ -z "$webm" ]; then
            echo "  warn: no webm in $d (segment skipped)"
            continue
        fi
        mp4="$OUT/seg${n}.mp4"
        ffmpeg -loglevel error -y -i "$webm" \
            -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
            -vf "fps=30,scale=1440:900:flags=lanczos" \
            "$mp4"
        echo "  wrote $mp4 ($(du -h "$mp4" | awk '{print $1}'))"
        n=$((n + 1))
    done

    # ── 4: Native Mac DMG launch via ffmpeg avfoundation ──────────────────
    if [ "${SKIP_NATIVE:-0}" != "1" ]; then
        echo
        echo "=== [3/4] Native Mac DMG launch (avfoundation, 25s) ==="
        if [ ! -d dist/Enclave.app ]; then
            echo "  warn: dist/Enclave.app not found — run ./scripts/build_mac.sh first"
        else
            # List avfoundation devices once for the operator's reference.
            echo "  Available capture devices:"
            ffmpeg -loglevel error -f avfoundation -list_devices true -i "" 2>&1 | \
                grep -E "AVFoundation|Capture screen" || true

            # Launch the .app in the background while we record.
            # The fresh first-run wizard appears because we point ENCLAVE
            # at a temp ~/.enclave with no setup_complete flag.
            export HOME="$(mktemp -d)/demo-home"
            mkdir -p "$HOME"

            open dist/Enclave.app &
            APP_PID=$!
            sleep 2  # let the window appear

            # Record screen 1, 25s, 30fps, scaled to 1440x900.
            # "1" is typically the main display index; adjust if multi-display.
            ffmpeg -loglevel error -y \
                -f avfoundation -framerate 30 -i "1:none" \
                -t 25 \
                -c:v libx264 -preset fast -crf 22 -pix_fmt yuv420p \
                -vf "scale=1440:900:force_original_aspect_ratio=decrease,pad=1440:900:(ow-iw)/2:(oh-ih)/2" \
                "$OUT/seg4.mp4" || echo "  warn: native capture failed (permissions?)"

            # Tidy up.
            osascript -e 'tell application "Enclave" to quit' 2>/dev/null || true
            kill $APP_PID 2>/dev/null || true
        fi
    else
        echo "  SKIP_NATIVE=1 — skipping segment 4"
    fi
fi

# ── Concatenate segments via ffmpeg concat demuxer ────────────────────────
echo
echo "=== [4/4] Concatenate segments → enclave-v1.1.1-demo.mp4 ==="
LIST="$OUT/concat.txt"
: > "$LIST"
for s in seg1 seg2 seg3 seg4; do
    [ -f "$OUT/$s.mp4" ] && echo "file '$s.mp4'" >> "$LIST"
done

if [ ! -s "$LIST" ]; then
    echo "  ERROR: no segments to concatenate"
    exit 1
fi

ffmpeg -loglevel error -y -f concat -safe 0 -i "$LIST" \
    -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
    -movflags +faststart \
    "$OUT/enclave-v1.1.1-demo.mp4"

echo "  wrote $OUT/enclave-v1.1.1-demo.mp4 ($(du -h "$OUT/enclave-v1.1.1-demo.mp4" | awk '{print $1}'))"
echo "  duration: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/enclave-v1.1.1-demo.mp4")s"
echo
echo "=== DONE ==="
