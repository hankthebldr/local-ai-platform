import * as React from 'react';

/** A small status dot; pulses with the teal heartbeat when `live`. */
export interface StatusPipProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Maps to a color. online=teal · running=info · success/warn/danger · idle=muted. */
  status?: 'online' | 'running' | 'success' | 'warn' | 'danger' | 'error' | 'idle';
  /** Animate the breathing halo. */
  live?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export function StatusPip(props: StatusPipProps): JSX.Element;
