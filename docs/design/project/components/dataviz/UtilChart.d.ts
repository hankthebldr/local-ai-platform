import * as React from 'react';

/** Resource utilization / throughput over time — calm area chart, mono axes. */
export interface UtilChartSeries {
  label: string;
  /** Values oldest → newest, plotted on a shared 0-max scale. */
  data: number[];
  /** Override the series color (defaults: accent → accent-2 → info). */
  color?: string;
}

export interface UtilChartProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Up to three series. More than three is a different problem. */
  series: UtilChartSeries[];
  width?: number;
  height?: number;
  /** Scale top (100 for %, or e.g. 64 for GB). Axes are always zero-based. */
  max?: number;
  /** Axis unit suffix. */
  unit?: string;
  /** X-axis labels, evenly spaced (e.g. ['-60m','-30m','now']). */
  xlabels?: string[];
  /** Dashed amber threshold line. */
  warn?: number;
}

export function UtilChart(props: UtilChartProps): JSX.Element;
