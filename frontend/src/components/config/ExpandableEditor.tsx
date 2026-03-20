/**
 * Monaco editor wrapper with an expand-to-modal button.
 *
 * Renders a compact inline editor with an expand icon in the top-right.
 * Clicking expand opens a near-fullscreen modal with a larger editor,
 * mirroring the pattern used by the chat PromptEditorModal.
 */

import React, { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';

interface ExpandableEditorProps {
  value: string;
  onChange: (value: string) => void;
  language?: string;
  height?: string;
  readOnly?: boolean;
  modalTitle?: string;
}

export const ExpandableEditor: React.FC<ExpandableEditorProps> = ({
  value,
  onChange,
  language = 'markdown',
  height = '200px',
  readOnly = false,
  modalTitle = 'Editor',
}) => {
  const [expanded, setExpanded] = useState(false);
  const [modalValue, setModalValue] = useState(value);

  useEffect(() => {
    if (expanded) setModalValue(value);
  }, [expanded]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!expanded) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onChange(modalValue);
        setExpanded(false);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [expanded, modalValue, onChange]);

  const editorOptions = {
    minimap: { enabled: false },
    wordWrap: 'on' as const,
    lineNumbers: 'on' as const,
    scrollBeyondLastLine: false,
    fontSize: 13,
    readOnly,
  };

  return (
    <>
      <div className="relative border border-gray-300 rounded overflow-hidden">
        <Editor
          height={height}
          defaultLanguage={language}
          value={value}
          onChange={(v) => onChange(v || '')}
          options={editorOptions}
        />
        <button
          type="button"
          onClick={() => setExpanded(true)}
          disabled={readOnly}
          className="absolute right-2 top-2 p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors disabled:opacity-50 z-10"
          title="Expand editor"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="15 3 21 3 21 9" />
            <polyline points="9 21 3 21 3 15" />
            <line x1="21" y1="3" x2="14" y2="10" />
            <line x1="3" y1="21" x2="10" y2="14" />
          </svg>
        </button>
      </div>

      {expanded && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white rounded-lg shadow-xl w-[85%] max-w-5xl h-[80%] max-h-[700px] flex flex-col">
            <div className="px-6 py-3 border-b flex items-center justify-between bg-gray-50 rounded-t-lg">
              <h3 className="text-sm font-semibold text-gray-800">{modalTitle}</h3>
              <button
                type="button"
                onClick={() => { onChange(modalValue); setExpanded(false); }}
                className="text-gray-500 hover:text-gray-700 p-1 hover:bg-gray-200 rounded transition-colors"
                title="Close (Esc)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              <Editor
                height="100%"
                defaultLanguage={language}
                value={modalValue}
                onChange={(v) => setModalValue(v || '')}
                options={{ ...editorOptions, fontSize: 14 }}
              />
            </div>
            <div className="px-6 py-3 border-t bg-gray-50 rounded-b-lg flex justify-end">
              <button
                type="button"
                onClick={() => { onChange(modalValue); setExpanded(false); }}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors text-sm"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
