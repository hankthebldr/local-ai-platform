import * as React from 'react';

/** Labeled 0-100 fit/score bar — model role-fit, bench scores, capacity. */
export interface FitBarProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Mono uppercase label, e.g. "coding". */
  label: string;
  /** 0-100. */
  value: number;
  /** Trailing mono hint, e.g. "best on fleet". */
  hint?: string;
  /** Bar fill color (defaults to accent teal). */
  color?: string;
  /** Show the numeric value. */
  showValue?: boolean;
}

export function FitBar(props: FitBarProps): JSX.Element;
