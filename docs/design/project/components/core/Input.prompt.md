Labelled text field — mono label, dark inset surface, teal focus ring.

```jsx
<Input label="Workflow ID" mono placeholder="my-workflow" required />
<Input label="Search" icon={<i data-lucide="search" />} placeholder="Filter models…" />
<Input label="Name" error="Already taken" defaultValue="triage" />
```

Pass `hint` for helper text, `error` for the danger state, `icon` for a leading glyph, `mono` to render IDs/code in JetBrains Mono.
