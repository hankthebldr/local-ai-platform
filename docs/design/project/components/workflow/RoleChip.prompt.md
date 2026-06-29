Draggable palette item for the Composer left rail — a role, agent, skill, plugin, or MCP that the user drags onto the canvas to add a step.

```jsx
<RoleChip kind="reasoning" title="reasoning" desc="Deep analysis · 34B class" />
<RoleChip kind="agent" title="xsiam-analyst" desc="Security triage persona" icon={<i data-lucide="bot" />} />
<RoleChip kind="skill" title="concise-writer" desc="Tightens prose on trigger" />
```

`kind` sets the left-marker tint and matches the palette tabs (Roles/Agents/Skills/Plugins/MCPs). The element is `draggable` by default.
