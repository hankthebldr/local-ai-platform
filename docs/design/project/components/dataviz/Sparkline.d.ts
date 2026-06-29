import * as React from 'react';

/** Tiny inline time-series — trends live next to the number they explain. */
export interface SparklineProps extends React.SVGAttributes<SVGSVGElement> {
  /** The series, oldest → newest. */
  data: number[];
  width?: number;
  height?: number;
  /** Stroke/fill color. Default accent teal. */
  color?: string;
  /** Soft area fill under the line. */
  fill?: boolean;
  strokeWidth?: number;
  /** Mark the latest point. */
  dot?: boolean;
  /** Fixed scale bounds (defaults to data extent). */
  max?: number;
  min?: number;
}

export function Sparkline(props: SparklineProps): JSX.Element;
