import * as React from 'react';

/** Labelled dropdown matching Input styling, with a custom caret. */
export interface SelectOption { value: string; label: string; }
export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: React.ReactNode;
  /** Options as strings or {value,label}. Omit and pass <option> children instead. */
  options?: Array<string | SelectOption>;
  /** Render the field in the mono face. */
  mono?: boolean;
  children?: React.ReactNode;
}

export function Select(props: SelectProps): JSX.Element;
