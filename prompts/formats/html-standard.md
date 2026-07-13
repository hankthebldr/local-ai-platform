---
name: HTML Standard
summary: Single-file, self-contained HTML page — no external fetches, Enclave token conventions.
target: html
version: 1
---
Produce a single self-contained HTML document.

- Emit ONE `.html` file. No external requests of any kind: inline all CSS in a `<style>` block, inline all JavaScript in a `<script>` block, and embed any images/fonts as `data:` URIs. No CDN links, no `<link rel="stylesheet">`, no remote `<script src>`.
- Do not include `<!DOCTYPE>` boilerplate commentary in prose — return only the markup.
- Use the Enclave design tokens: warm-charcoal surfaces, teal accent, generous spacing; prefer CSS custom properties (`--bg`, `--fg`, `--accent`) declared once on `:root`.
- The page MUST render correctly opened directly from disk (`file://`) with no network.
- Keep it responsive: relative units, `max-width: 100%` on media, no horizontal body scroll.
