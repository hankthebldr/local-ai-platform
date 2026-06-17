import * as React from 'react';

/** The unified drill-down card — one anatomy for every entity type. */
export interface EntityCardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Mono entity id (model name, agent name, workflow slug…). */
  id: string;
  /** Entity type label shown in the corner badge. */
  type?: 'model' | 'agent' | 'skill' | 'plugin' | 'mcp' | 'context' | 'workflow' | 'run' | 'chat';
  /** Status pip. */
  status?: 'online' | 'idle' | 'error';
  /** Mono meta line, e.g. "4.7 GB · Q4_K_M · 47 tok/s". */
  meta?: string;
  /** Sans one-liner description. */
  desc?: string;
  /** Role-fit bars — label → 0-100. */
  fits?: Record<string, number>;
  /** Dependents summary for the footer, e.g. "3 steps · 2 agents". */
  usedBy?: string;
  /** Selected (peek open) state. */
  selected?: boolean;
  /** Footer action nodes (chips/buttons). */
  actions?: React.ReactNode;
}

export function EntityCard(props: EntityCardProps): JSX.Element;
