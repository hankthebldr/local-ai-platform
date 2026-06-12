import * as React from 'react';

/** Unified install wizard phase header — source → configure → verify → land. */
export interface WizardStepperProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Phase labels. Default: ['source','configure','verify','land']. */
  phases?: string[];
  /** Index of the active phase. */
  active?: number;
}

export function WizardStepper(props: WizardStepperProps): JSX.Element;
