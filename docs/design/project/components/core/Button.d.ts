import * as React from 'react';

/**
 * Enclave's primary action control. Mono-label face, restrained radius,
 * teal primary. Use for any clickable command in the console.
 *
 * @startingPoint section="Core" subtitle="Action button — 5 variants, 3 sizes" viewport="700x150"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual weight. primary=teal fill · secondary=emerald · ghost=quiet · warm=ember · danger=coral */
  variant?: 'primary' | 'secondary' | 'ghost' | 'warm' | 'danger';
  /** Control size. */
  size?: 'sm' | 'md' | 'lg';
  /** Optional leading icon node (e.g. a Lucide <i> or inline SVG). */
  icon?: React.ReactNode;
  /** Replaces the icon with a spinner and disables the button. */
  loading?: boolean;
  disabled?: boolean;
  children?: React.ReactNode;
}

export function Button(props: ButtonProps): JSX.Element;
