The signature Enclave container — a bordered surface with corner registration ticks and a caps-tracked mono label. Frame every console region with it.

```jsx
<Panel label="Workflow Composer" headerExtra={<Button size="sm" variant="ghost">Save</Button>}>
  …canvas…
</Panel>

<Panel label="System Prompt" ticks translucent>…</Panel>
<Panel active>…live run…</Panel>
```

`label` renders the mono header (with a leading teal tick). `translucent` + blur for floating popovers/toolbars. `active` adds the teal glow. `ticks={false}` to drop the corner marks.
