import * as React from 'react';

/** Small mono action/suggestion chip — message hover actions + next-best-action nudges. */
export interface ActionChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Leading icon node. */
  icon?: React.ReactNode;
  /** Accent (teal) emphasis — the recommended action. */
  accent?: boolean;
  /** Larger size for next-best-action nudges above the composer. */
  lg?: boolean;
  /** Show a dismiss × (nudges are dismissible, never modal). */
  onDismiss?: (e: React.MouseEvent) => void;
}

export function ActionChip(props: ActionChipProps): JSX.Element;
