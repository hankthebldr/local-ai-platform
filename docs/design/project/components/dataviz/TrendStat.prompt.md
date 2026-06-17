A metric with memory — the upgrade from MetricStat when "now" isn't enough. Mono label, big mono value, a delta against the previous period, and a sparkline of how it got here. Use in run summaries, model peeks, and fleet readouts.

```jsx
<TrendStat label="throughput" value="47 tok/s" delta="+12%" data={tpsWeek} />
<TrendStat label="avg run" value="0:41" delta="-9s" deltaGood={false} data={durWeek} color="var(--accent-2)" />
<TrendStat label="mem peak" value="52 GB" delta="+6 GB" deltaGood={false} data={memWeek} />
```

`deltaGood={false}` flips the delta colors for metrics where up is bad (latency, memory pressure, error rate). Deltas compare like periods — never invent one.
