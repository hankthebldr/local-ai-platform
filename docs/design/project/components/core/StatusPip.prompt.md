A small status dot that breathes with the teal heartbeat when live — the "something is alive" signal.

```jsx
<StatusPip status="online" live />
<StatusPip status="running" live size="lg" />
<StatusPip status="idle" />
```

`status` picks the hue (online=teal, running=info, success/warn/danger, idle=muted). `live` turns on the pulse. Pair with a mono label for system-health strips.
