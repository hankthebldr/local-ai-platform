import * as React from 'react';

/** Compact key/value system metric (CPU, MEM, Loaded, Version). */
export interface MetricStatProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Caps mono key. */
  label: React.ReactNode;
  /** The value (e.g. "34%", "18.2 / 64 GB"). */
  value: React.ReactNode;
  /** Optional sub-detail line. */
  sub?: React.ReactNode;
  /** 0–100 load — auto-colors teal→amber→coral and feeds the bar. */
  percent?: number | null;
  /** Force a color (overrides the load color). */
  color?: string;
  /** Show a thin load bar (needs percent). */
  bar?: boolean;
  /** Lay key + value on one row instead of stacked. */
  row?: boolean;
}

export function MetricStat(props: MetricStatProps): JSX.Element;
