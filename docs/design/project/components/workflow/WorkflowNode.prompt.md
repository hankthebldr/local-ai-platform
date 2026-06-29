A single workflow step rendered as a DAG node — role-tinted top rule, title, model meta, connection ports, and a run-status pip. The core unit of the Composer canvas.

```jsx
<WorkflowNode title="analyze" role="reasoning" model="dolphin-mixtral" status="success" outLinked />
<WorkflowNode title="generate" role="coding" model="qwen2.5-coder" status="running" selected inLinked />
<WorkflowNode title="validate" role="fast" model="llama3.2:3b" />
```

`role` tints the top rule (reasoning=teal, coding=sky, fast=amber, general=emerald, uncensored=ember). `status` drives the pip; `selected` adds the teal glow; `inLinked`/`outLinked` paint connected ports. Renders a Lucide `box` icon — call `lucide.createIcons()` after mount.
