/**
 * McpAgentChoice: the "Which agent uses it?" radio group on the MCP Server add and edit panels.
 * Data analyst comes first. Each label is the bold agent name, " · ", then its hint.
 */
import React, { useId } from 'react';
import type { McpAgentName } from '../../types/agentConfig';
import { MCP_AGENT_LABELS, MCP_AGENT_HINTS } from '../../types/agentConfig';

const AGENTS: McpAgentName[] = ['data_analyst', 'architect'];

export const McpAgentChoice: React.FC<{
  value: McpAgentName;
  onChange: (agent: McpAgentName) => void;
}> = ({ value, onChange }) => {
  const groupName = useId();
  return (
    <fieldset className="mb-3">
      <legend className="block text-sm text-gray-500 mb-1">Which agent uses it?</legend>
      {AGENTS.map(agent => (
        <label key={agent} className="flex items-center gap-2 py-0.5 text-sm text-gray-700 cursor-pointer">
          <input
            type="radio"
            name={groupName}
            value={agent}
            checked={value === agent}
            onChange={() => onChange(agent)}
          />
          <span>
            <strong>{MCP_AGENT_LABELS[agent]}</strong>
            {` · ${MCP_AGENT_HINTS[agent]}`}
          </span>
        </label>
      ))}
    </fieldset>
  );
};
