Compact on/off switch with a teal track. Controlled or uncontrolled.

```jsx
<Toggle label="Stream tokens" defaultChecked />
<Toggle checked={authOn} onChange={e => setAuthOn(e.target.checked)} label="API auth" />
<Toggle size="sm" />
```

Sizes `sm`/`md`. Provide `checked`+`onChange` to control it, or `defaultChecked` to leave it uncontrolled.
