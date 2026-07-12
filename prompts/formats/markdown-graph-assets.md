---
name: Markdown Graph Assets
summary: Obsidian-style markdown — [[wikilinks]], a MOC with checkbox grammar, relative asset paths.
target: markdown
version: 1
---
Produce linked markdown suitable for an Obsidian-style knowledge graph.

- Cross-reference other notes with `[[wikilinks]]` (bare note titles, no file extension).
- When enumerating work, use a Map-of-Content (MOC) with GitHub-flavoured checkbox grammar: `- [ ]` for pending, `- [x]` for done — matching `WorkspaceIndex.render_markdown` so a rendered index round-trips.
- Reference produced assets (images, attachments) with workspace-relative paths, never absolute host paths and never remote URLs.
- Lead each note with a single `#` H1 title line so it summarises cleanly.
- Keep front-matter minimal; put structure in headings, not YAML.
