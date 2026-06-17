Resource utilization / throughput over time. A calm area chart: hairline grid at 0/50/100, mono axis labels on the right, soft 8% area fills, up to three series, optional dashed warn threshold. Axes are always zero-based — never truncate a utilization axis.

```jsx
<UtilChart
  series={[{ label: 'cpu', data: cpuHour }, { label: 'mem', data: memHour }]}
  max={100} unit="%" warn={85}
  xlabels={['-60m', '-30m', 'now']} />
<UtilChart series={[{ label: 'tok/s', data: tpsHour }]} max={60} unit="" warn={null} />
```

The legend doubles as the live readout (label + latest value). Series color order: accent → accent-2 → info; warn/danger reserved for thresholds and failures.
