import * as React from 'react';

/** Small status / category pill in a semantic tone. */
export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  children?: React.ReactNode;
  /** Semantic color. */
  tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info' | 'warm';
  /** Show a leading status dot. */
  dot?: boolean;
  /** Use the square (chip) radius instead of pill. */
  square?: boolean;
  /** Solid fill instead of ghost (accent/success only). */
  solid?: boolean;
}

export function Badge(props: BadgeProps): JSX.Element;
