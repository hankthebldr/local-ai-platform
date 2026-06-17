Tiny inline time-series — the default unit of data visualization in Enclave. Trends render next to the number they explain (a metric, a model card, a run row), never on a separate dashboard page.

```jsx
<Sparkline data={[31, 35, 33, 41, 38, 47, 44, 47]} />
<Sparkline data={memSeries} color="var(--accent-2)" width={90} height={22} />
<Sparkline data={errRate} color="var(--warn)" fill={false} max={100} min={0} />
```

Pass `max`/`min` to fix the scale (0-100 for utilization). Color order for series: accent → accent-2 → info; warn/danger only for thresholds and failures.
