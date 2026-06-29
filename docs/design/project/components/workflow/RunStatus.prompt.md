Live workflow-run progress strip — a pulsing status pip, a state label, the current step, a thin progress bar, and an `n/total` counter. Floats over the canvas during a run and heads each row in the Runs list.

```jsx
<RunStatus state="running" current="generate" step={2} total={4} />
<RunStatus state="success" step={4} total={4} />
<RunStatus state="error" current="validate" step={3} total={4} />
```

`state` drives color + label (running pulses). Pass `step`/`total` for the bar and counter; `showBar={false}` for a compact chip.
