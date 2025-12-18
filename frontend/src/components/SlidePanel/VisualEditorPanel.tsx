import React, { useState, useMemo, useEffect } from 'react';
import type { SlideDeck, Slide } from '../../types/slide';
import type { EditableNode } from './visualEditor.types';
import { buildEditableTree, applyTextChange, buildPreviewHtml, getDefaultExpandedIds } from './treeParser';
import { ElementTreeView } from './ElementTreeView';

interface VisualEditorPanelProps {
  html: string;
  slideDeck: SlideDeck;
  slide: Slide;
  onChange: (html: string) => void;
}

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
const PREVIEW_SCALE = 0.5;

export const VisualEditorPanel: React.FC<VisualEditorPanelProps> = ({
  html,
  slideDeck,
  slide,
  onChange,
}) => {
  // Parse HTML into editable tree
  const nodes = useMemo(() => buildEditableTree(html), [html]);
  
  // Track expanded nodes
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => 
    getDefaultExpandedIds(nodes)
  );
  
  // Update expanded IDs when nodes change (new HTML)
  useEffect(() => {
    setExpandedIds(getDefaultExpandedIds(nodes));
  }, [nodes]);
  
  // Build preview HTML
  const previewHtml = useMemo(() => 
    buildPreviewHtml(html, slideDeck.css, slideDeck.external_scripts, slide.scripts),
    [html, slideDeck.css, slideDeck.external_scripts, slide.scripts]
  );
  
  const handleToggleExpand = (nodeId: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };
  
  const handleTextChange = (nodeId: string, newText: string) => {
    const updatedHtml = applyTextChange(html, nodeId, newText);
    onChange(updatedHtml);
  };
  
  // Expand all nodes
  const handleExpandAll = () => {
    const allIds = new Set<string>();
    const collectIds = (nodeList: EditableNode[]) => {
      nodeList.forEach(node => {
        if (node.children.length > 0) {
          allIds.add(node.id);
          collectIds(node.children);
        }
      });
    };
    collectIds(nodes);
    setExpandedIds(allIds);
  };
  
  // Collapse all nodes
  const handleCollapseAll = () => {
    setExpandedIds(new Set());
  };
  
  return (
    <div className="flex h-full">
      {/* Left panel: Slide Content */}
      <div className="w-1/2 border-r overflow-y-auto bg-white">
        {/* Header with controls */}
        <div className="sticky top-0 z-10 bg-white border-b px-4 py-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-gray-700">Slide Content</h3>
          <div className="flex gap-2">
            <button
              onClick={handleExpandAll}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              Expand All
            </button>
            <span className="text-gray-300">|</span>
            <button
              onClick={handleCollapseAll}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              Collapse All
            </button>
          </div>
        </div>
        
        {/* Tree content */}
        <ElementTreeView
          nodes={nodes}
          expandedIds={expandedIds}
          onToggleExpand={handleToggleExpand}
          onTextChange={handleTextChange}
        />
        
        {/* Help text */}
        <div className="px-4 py-3 border-t bg-gray-50 text-xs text-gray-500">
          <p>Click any text to edit it</p>
        </div>
      </div>
      
      {/* Right panel: Preview */}
      <div className="w-1/2 bg-gray-100 overflow-hidden flex flex-col">
        <div className="sticky top-0 z-10 bg-gray-100 border-b px-4 py-2">
          <h3 className="text-sm font-medium text-gray-700">Preview</h3>
        </div>
        
        <div className="flex-1 p-4 overflow-auto">
          <div 
            className="relative bg-white shadow-lg rounded overflow-hidden"
            style={{
              width: `${SLIDE_WIDTH * PREVIEW_SCALE}px`,
              height: `${SLIDE_HEIGHT * PREVIEW_SCALE}px`,
            }}
          >
            <iframe
              srcDoc={previewHtml}
              title="Slide Preview"
              className="absolute top-0 left-0 border-0"
              sandbox="allow-scripts"
              style={{
                width: `${SLIDE_WIDTH}px`,
                height: `${SLIDE_HEIGHT}px`,
                transform: `scale(${PREVIEW_SCALE})`,
                transformOrigin: 'top left',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};
