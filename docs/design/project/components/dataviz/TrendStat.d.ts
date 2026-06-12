import * as React from 'react';

/** A metric with memory — value, delta vs previous period, sparkline. */
export interface TrendStatProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Mono uppercase label, e.g. "throughput". */
  label: string;
  /** The current value, preformatted ("47 tok/s", "0:41"). */
  value: string;
  /** Delta vs the previous period ("+12%", "-3"). Leading '-' renders ▾. */
  delta?: string;
  /** Is an increase good? (false for latency, error rate, memory pressure). */
  deltaGood?: boolean;
  /** Sparkline series, oldest → newest. */
  data?: number[];
  /** Sparkline color. */
  color?: string;
  sparkWidth?: number;
}

export function TrendStat(props: TrendStatProps): JSX.Element;
