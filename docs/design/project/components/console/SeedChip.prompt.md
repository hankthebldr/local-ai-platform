Key:value chip describing a thread's seed — role, model, context, plugin or agent. Seeding happens in the composer, and these chips persist in the thread header so the seed is always visible.

```jsx
<SeedChip k="role" v="reasoning" />
<SeedChip k="model" v="dolphin-mixtral" />
<SeedChip k="ctx" v="xsiam-docs" tone="accent" />
<SeedChip v="+ context" ghost />
```

`tone="accent"` marks attached context/plugins; `ghost` is the dashed add-affordance.
