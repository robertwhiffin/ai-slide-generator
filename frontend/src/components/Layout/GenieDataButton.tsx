import React, { useState, useRef, useEffect } from 'react';
import { Database } from 'lucide-react';
import { useAgentConfig } from '../../contexts/AgentConfigContext';
import { useSession } from '../../contexts/SessionContext';
import { api } from '../../services/api';
import type { GenieTool } from '../../types/agentConfig';

export const GenieDataButton: React.FC = () => {
  const { agentConfig } = useAgentConfig();
  const { sessionId } = useSession();
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const genieTools = agentConfig.tools.filter(
    (t): t is GenieTool => t.tool_type === 'genie'
  );

  // Close dropdown on outside click
  useEffect(() => {
    if (!showDropdown) return;
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showDropdown]);

  if (genieTools.length === 0) {
    return null;
  }

  const openGenieLink = async (spaceId: string) => {
    if (!sessionId) return;
    try {
      const result = await api.getGenieLink(sessionId, spaceId);
      if (result.url) {
        window.open(result.url, '_blank');
      } else {
        alert(result.message || 'No Genie queries in this session yet');
      }
    } catch (err) {
      console.error('Failed to get Genie link:', err);
      alert('Failed to get Genie conversation link');
    }
    setShowDropdown(false);
  };

  const handleClick = async () => {
    if (genieTools.length === 1) {
      const tool = genieTools[0];
      if (!tool.conversation_id) {
        alert('No Genie queries in this session yet');
        return;
      }
      await openGenieLink(tool.space_id);
    } else {
      setShowDropdown(v => !v);
    }
  };

  return (
    <div className="relative shrink-0" ref={dropdownRef}>
      <button
        onClick={handleClick}
        className="px-3 py-1.5 rounded text-sm transition-colors flex items-center gap-1.5 bg-purple-500 hover:bg-purple-700 text-white"
      >
        <Database size={14} />
        Genie Data
      </button>

      {showDropdown && genieTools.length > 1 && (
        <div className="absolute right-0 mt-2 w-64 bg-white rounded-lg shadow-lg border border-purple-200 py-1 z-50">
          <div className="px-3 py-2 border-b border-gray-100">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
              Genie Conversations ({genieTools.length})
            </p>
          </div>
          {genieTools.map(tool => (
            <button
              key={tool.space_id}
              onClick={() => {
                if (!tool.conversation_id) {
                  alert('No Genie queries in this session yet');
                  setShowDropdown(false);
                  return;
                }
                openGenieLink(tool.space_id);
              }}
              className="w-full text-left px-3 py-2.5 flex items-center gap-2.5 text-sm text-gray-700 hover:bg-purple-50 transition-colors border-b border-gray-50 last:border-0"
            >
              <Database size={14} className="text-purple-500 shrink-0" />
              <span className="truncate">{tool.space_name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
