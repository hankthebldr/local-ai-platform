# Enclave v1.1.1 — Demo Assets

Walkthrough stills and recorder scripts for the v1.1.1 release.

The full MP4 walkthrough (`enclave-v1.1.1-demo.mp4`) is built locally by
[scripts/record_demo.sh](../../scripts/record_demo.sh) and lands in
`dist/demo/` (gitignored). Upload it to the release / PR comment as an
attachment.

## Stills

| File | Surface | What's visible |
|---|---|---|
| [seg1_p50.png](seg1_p50.png) | Composer-as-dashboard + Agents workbench | Cortex Console rebrand (PR #57), workbench sub-tabs (Steps · Agents · Skills · Plugins), system rail showing API · Ollama · Models · v1.1.1 |
| [seg2_p50.png](seg2_p50.png) | Workflow Index (OOTB catalogue) | 5 OOTB workflows from PR #56 visible as cards (XQL/XDM bundle) |
| [seg3_p50.png](seg3_p50.png) | Context tab — Documents drop-zone | RAG drop-zone (PR #55), pre-indexed document, embedding backend status |

## Producing the MP4

```bash
# One-time: install Playwright Chromium
./venv/bin/playwright install chromium

# Disable API auth for clean visuals
echo "ENABLE_API_AUTH=false" > .env.demo
docker compose --env-file .env.demo up -d api

# Record browser segments only (safe, no permission prompts)
SKIP_NATIVE=1 ./scripts/record_demo.sh

# Output:
# dist/demo/seg{1,2,3}.mp4 — individual segments
# dist/demo/enclave-v1.1.1-demo.mp4 — concatenated walkthrough
```

## Segment 4 — Native Mac DMG first-run

Requires:

1. **Stop docker** to free port 8000: `docker compose down`
2. **macOS Screen Recording permission** for the terminal / ffmpeg process.
   First run will trigger the system dialog — grant it via `System Settings
   → Privacy & Security → Screen & System Audio Recording`, then restart the
   terminal.
3. **Pre-built `dist/Enclave.app`** from `./scripts/build_mac.sh`.

Then:

```bash
./scripts/record_demo.sh        # no SKIP_NATIVE — runs all 4 segments
```

This:
- Launches `dist/Enclave.app` against a temp `$HOME` so the first-run wizard
  appears.
- Records 25 s of screen capture via `ffmpeg avfoundation`.
- Concatenates as `seg4.mp4`.
- Stitches all four segments into the final walkthrough.

## Demo agenda (per release)

The script is designed to be re-run on every tag — same selectors, fresh
recording against whatever has shipped. Update the segment scripts in
`scripts/record_demo.py` when the dashboard IA changes (e.g. PR #57 moved
the composer to the dashboard, so segment 1 now starts at `/`).

Narration: the recording is silent and timing-accurate (~3 s pauses
between actions) so it can be voice-overed in post.
