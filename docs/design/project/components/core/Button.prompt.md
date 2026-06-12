Enclave's primary action control — a mono-label button used for every command in the console; teal primary, with secondary/ghost/warm/danger variants.

```jsx
<Button variant="primary" size="md" onClick={runWorkflow}>Run ▶</Button>
<Button variant="ghost" icon={<i data-lucide="plus" />}>New Project</Button>
<Button variant="secondary" size="sm">Export YAML</Button>
<Button variant="danger" loading>Deleting…</Button>
```

Variants: `primary` (teal fill, the main CTA), `secondary` (emerald), `ghost` (quiet, for toolbars), `warm` (ember — sparing), `danger` (coral). Sizes `sm`/`md`/`lg`. Pass `loading` for an inline spinner, `icon` for a leading glyph. Hover lifts 1px; primary gains a teal glow.
