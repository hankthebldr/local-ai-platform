import * as React from 'react';

/** Labelled text field with mono label, dark inset, teal focus ring. */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Caps-tracked mono label above the field. */
  label?: React.ReactNode;
  /** Helper text below the field. */
  hint?: React.ReactNode;
  /** Error message — paints the field in the danger state. */
  error?: React.ReactNode;
  /** Leading icon node. */
  icon?: React.ReactNode;
  /** Mark required (teal asterisk). */
  required?: boolean;
  /** Render the value in the mono face (for IDs / code). */
  mono?: boolean;
}

export function Input(props: InputProps): JSX.Element;
