import * as React from 'react';

/** Square icon-only control for toolbars and canvas chrome. */
export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Icon node (Lucide <i> or inline SVG or a glyph). */
  children?: React.ReactNode;
  /** Accessible label (also the tooltip). */
  label?: string;
  size?: 'sm' | 'md' | 'lg';
  /** Render in the selected/active teal state. */
  active?: boolean;
  /** Transparent until hover (for dense toolbars). */
  bare?: boolean;
  disabled?: boolean;
}

export function IconButton(props: IconButtonProps): JSX.Element;
