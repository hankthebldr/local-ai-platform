import * as React from 'react';

/** Workflow-run progress strip: status pip + label + step counter + bar. */
export interface RunStatusProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Run state — drives color, label, and pip pulse. */
  state?: 'running' | 'success' | 'error' | 'queued' | 'idle';
  /** Current step name (truncates). */
  current?: string;
  /** Completed step index. */
  step?: number;
  /** Total steps (drives the bar + counter). */
  total?: number;
  /** Show the progress bar. */
  showBar?: boolean;
}

export function RunStatus(props: RunStatusProps): JSX.Element;
