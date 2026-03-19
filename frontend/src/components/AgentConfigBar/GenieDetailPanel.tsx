import React, { useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { AvailableTool, GenieTool } from '../../types/agentConfig';
import { toGenieToolEntry } from './toolUtils';

interface GenieDetailPanelProps {
  tool: GenieTool | AvailableTool;
  mode: 'add' | 'edit';
  onSave: (tool: GenieTool) => void;
  onCancel: () => void;
}

export default function GenieDetailPanel({ tool, mode, onSave, onCancel }: GenieDetailPanelProps) {
  const [description, setDescription] = useState(tool.description ?? '');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onCancel();
    }
  };

  const handleSave = () => {
    let entry: GenieTool;

    if (tool.type === 'genie' && 'space_id' in tool && mode === 'edit') {
      entry = {
        ...tool,
        type: 'genie',
        description,
      } as GenieTool;
      if ('conversation_id' in tool) {
        (entry as GenieTool & { conversation_id?: string }).conversation_id = (
          tool as GenieTool & { conversation_id?: string }
        ).conversation_id;
      }
    } else {
      entry = {
        ...toGenieToolEntry(tool as AvailableTool),
        description,
      };
    }

    onSave(entry);
  };

  const spaceName = tool.space_name ?? tool.space_id ?? '';
  const spaceId = tool.space_id ?? '';

  return (
    <div
      data-testid="genie-detail-panel"
      className="border rounded bg-gray-50 p-4"
      onKeyDown={handleKeyDown}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="bg-blue-500 text-white uppercase text-[10px] font-bold px-1.5 py-0.5 rounded">
            Genie
          </span>
          <span className="font-semibold">{spaceName}</span>
        </div>
        <button
          onClick={onCancel}
          className="text-gray-400 hover:text-gray-600"
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      {/* Space ID */}
      <div className="mb-3">
        <label className="block text-sm text-gray-500 mb-1">Space ID</label>
        <div className="font-mono text-sm text-gray-700">{spaceId}</div>
      </div>

      {/* Description */}
      <div className="mb-4">
        <div className="flex items-baseline justify-between mb-1">
          <label className="text-sm text-gray-500">Description</label>
          <span className="text-xs text-gray-400">
            Used by the agent to decide when to query this space
          </span>
        </div>
        <textarea
          ref={textareaRef}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe when the agent should use this space..."
          className="w-full border rounded px-3 py-2 text-sm resize-y min-h-[80px] focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      {/* Buttons */}
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          {mode === 'add' ? 'Save & Add' : 'Save'}
        </button>
      </div>
    </div>
  );
}
