import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { Message as MessageType } from '../../types/message';
import { TOOL_TYPE_LABELS } from '../../types/agentConfig';

const MAX_LEN = 120;

const truncate = (text: string): string =>
  text.length > MAX_LEN ? `${text.slice(0, MAX_LEN)}…` : text;

const displayName = (name: string): string =>
  Object.prototype.hasOwnProperty.call(TOOL_TYPE_LABELS, name)
    ? TOOL_TYPE_LABELS[name as keyof typeof TOOL_TYPE_LABELS]
    : name;

interface ActivityItem {
  name: string;
  summary: string;
  result?: string;
}

const summariseArgs = (name: string, args: Record<string, unknown> | undefined): string => {
  const a = args ?? {};
  if (name === 'genie_one' && typeof a.question === 'string') return truncate(a.question);
  const text = Object.entries(a)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : String(v)}`)
    .join(', ');
  return truncate(text);
};

/** Pair each call with the result that follows it; an orphan result becomes its own item. */
function buildActivityItems(messages: MessageType[]): ActivityItem[] {
  const items: ActivityItem[] = [];
  let last: ActivityItem | null = null;
  for (const m of messages) {
    if (m.tool_call) {
      last = {
        name: displayName(m.tool_call.name),
        summary: summariseArgs(m.tool_call.name, m.tool_call.arguments),
      };
      items.push(last);
    } else if (m.role === 'tool') {
      if (last && last.result === undefined) {
        last.result = truncate(m.content ?? '');
      } else {
        last = {
          name: displayName(m.tool_call_id ?? 'tool'),
          summary: '',
          result: truncate(m.content ?? ''),
        };
        items.push(last);
      }
    }
  }
  return items;
}

export const ToolActivityBar: React.FC<{ messages: MessageType[] }> = ({ messages }) => {
  const [expanded, setExpanded] = useState(false);
  const items = buildActivityItems(messages);
  const names = Array.from(new Set(items.map((i) => i.name)));
  const Chevron = expanded ? ChevronDown : ChevronRight;
  const label = `${items.length} tool ${items.length === 1 ? 'call' : 'calls'} · ${names.join(', ')}`;

  return (
    <div data-testid="tool-activity-bar" className="ml-6 text-xs text-muted-foreground">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 hover:text-foreground"
      >
        <Chevron className="size-3" />
        <span>{label}</span>
      </button>
      {expanded && (
        <ul className="mt-1 ml-4 space-y-0.5">
          {items.map((item, i) => (
            <li key={i} data-testid="tool-activity-item">
              <div>
                <span className="font-medium">{item.name}</span>
                {item.summary && <span>{` · ${item.summary}`}</span>}
              </div>
              {item.result !== undefined && <div className="opacity-70">{item.result}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
