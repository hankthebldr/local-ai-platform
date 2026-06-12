import * as React from 'react';

/**
 * The signature Enclave framed container: bordered surface with corner
 * registration ticks and a caps-tracked mono label. Wrap any console region.
 *
 * @startingPoint section="Core" subtitle="Blueprint panel with corner ticks + mono label" viewport="700x200"
 */
export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode;
  /** Caps-tracked mono label shown in the header. */
  label?: React.ReactNode;
  /** Right-aligned header content (buttons, badges). */
  headerExtra?: React.ReactNode;
  /** Show the corner registration ticks. Default true. */
  ticks?: boolean;
  /** Translucent surface + backdrop blur (for floating chrome). */
  translucent?: boolean;
  /** Square off the corners (radius 0). */
  flush?: boolean;
  /** Active state — teal glow ring. */
  active?: boolean;
  /** Padding override (px number or CSS length). */
  pad?: number | string;
}

export function Panel(props: PanelProps): JSX.Element;
