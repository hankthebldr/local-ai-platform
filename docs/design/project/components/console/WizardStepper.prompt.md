Phase header for the unified install wizard — the same four phases for every object type (model, agent, skill, plugin/MCP, workflow): source → configure → verify → land. Verify is always a conversation: you talk to the thing before it lands.

```jsx
<WizardStepper active={0} />
<WizardStepper active={2} />
<WizardStepper phases={['pick', 'tune', 'try', 'ship']} active={1} />
```
