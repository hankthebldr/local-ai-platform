Compact system metric — a mono caps key over a value, with optional load bar that auto-colors teal→amber→coral as it climbs. Used in the Composer's system-impact strip.

```jsx
<MetricStat label="CPU" value="34%" percent={34} bar />
<MetricStat label="MEM" value="18.2 / 64 GB" sub="28% used" percent={28} bar />
<MetricStat label="Loaded" value="3" row />
```

Pass `percent` for auto load-coloring + the bar, or `color` to force one. `row` lays key/value inline for dense strips.
