import * as React from 'react';

/** Compact switch — teal track when on. Controlled or uncontrolled. */
export interface ToggleProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size' | 'onChange'> {
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  /** Inline label to the right of the switch. */
  label?: React.ReactNode;
  size?: 'sm' | 'md';
  disabled?: boolean;
}

export function Toggle(props: ToggleProps): JSX.Element;
