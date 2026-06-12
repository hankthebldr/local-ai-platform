The unified drill-down card — same anatomy for models, agents, skills, plugins, contexts, workflows, runs and chats: status pip + mono id + type badge, mono meta line, optional role-fit bars, dependents footer. Click opens a peek panel; the header invariant repeats in peek and full-page views.

```jsx
<EntityCard id="qwen2.5-coder" type="model" status="online"
  meta="4.7 GB · Q4_K_M · 47 tok/s"
  fits={{ coding: 90, reasoning: 40, fast: 65 }}
  usedBy="3 steps · 2 agents · 1 workflow" />
<EntityCard id="xsiam-analyst" type="agent" status="online"
  meta="reasoning · dolphin-mixtral" desc="Security triage persona"
  usedBy="2 steps · 3 threads" />
```

`fits` renders label → 0-100 bars. `usedBy` answers "what depends on this?" — the Usage tab's one-line summary.
