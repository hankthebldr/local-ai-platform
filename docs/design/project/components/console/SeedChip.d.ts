import * as React from 'react';

/** Key:value chip for a thread's seed — role, model, context, plugin, agent. */
export interface SeedChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Mono uppercase key, e.g. "role", "model", "ctx". Omit for a bare value chip. */
  k?: string;
  /** The value, e.g. "reasoning", "dolphin-mixtral". */
  v: string;
  /** 'accent' highlights attached context/plugins. */
  tone?: 'neutral' | 'accent';
  /** Dashed affordance chip ("+ context"). */
  ghost?: boolean;
  /** Show a remove ×. */
  onRemove?: (e: React.MouseEvent) => void;
}

export function SeedChip(props: SeedChipProps): JSX.Element;
