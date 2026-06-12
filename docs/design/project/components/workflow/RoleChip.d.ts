import * as React from 'react';

/** Draggable palette item — a role, agent, skill, plugin, or MCP server. */
export interface RoleChipProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Mono title (the role/agent/skill name). */
  title: string;
  /** Optional one-line description. */
  desc?: string;
  /** Palette kind — drives the tint marker. */
  kind?: 'reasoning' | 'coding' | 'fast' | 'general' | 'uncensored' | 'agent' | 'skill' | 'plugin' | 'mcp';
  /** Leading icon node. */
  icon?: React.ReactNode;
  /** Show the drag grip. */
  grip?: boolean;
}

export function RoleChip(props: RoleChipProps): JSX.Element;
