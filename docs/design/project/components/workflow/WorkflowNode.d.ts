import * as React from 'react';

/**
 * A single step on the Composer DAG canvas — role-tinted card with title,
 * model meta, IO ports, and a run-status pip. The atom of the workflow UI.
 *
 * @startingPoint section="Workflow" subtitle="DAG step node for the Composer canvas" viewport="700x220"
 */
export interface WorkflowNodeProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Step name. */
  title?: string;
  /** Role — drives the top-rule tint. */
  role?: 'reasoning' | 'coding' | 'fast' | 'general' | 'uncensored';
  /** Model id shown in the meta row. */
  model?: string;
  /** Run status — drives the pip color. */
  status?: 'idle' | 'running' | 'success' | 'error';
  /** Teal glow selected state. */
  selected?: boolean;
  inPort?: boolean;
  outPort?: boolean;
  /** Paint the input/output port as connected. */
  inLinked?: boolean;
  outLinked?: boolean;
  children?: React.ReactNode;
}

export function WorkflowNode(props: WorkflowNodeProps): JSX.Element;
