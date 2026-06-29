import * as React from 'react';

/** Adoption-ladder dots — how far a thread has graduated (seed → operate). */
export interface MaturityMeterProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Rungs reached, 0-total. */
  value: number;
  /** Rung count. */
  total?: number;
  /** Glow the next rung (a graduation is available, e.g. convert unlocked). */
  hot?: boolean;
  /** Optional leading mono label. */
  label?: string;
}

export function MaturityMeter(props: MaturityMeterProps): JSX.Element;
