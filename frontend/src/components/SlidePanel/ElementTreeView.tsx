import React, { useState, useRef, useEffect } from 'react';
import { FiChevronRight, FiLock } from 'react-icons/fi';
import type { EditableNode } from './visualEditor.types';

interface ElementTreeViewProps {
  nodes: EditableNode[];
  expandedIds: Set<string>;
  onToggleExpand: (nodeId: string) => void;
  onTextChange: (nodeId: string, newText: string) => void;
}

interface TreeNodeProps {
  node: EditableNode;
  depth: number;
  isExpanded: boolean;
  expandedIds: Set<string>;
  onToggleExpand: (nodeId: string) => void;
  onTextChange: (nodeId: string, newText: string) => void;
}

interface TextEditorProps {
  value: string;
  onSave: (newValue: string) => void;
  onCancel: () => void;
}

// Map HTML elements to friendly labels
function getFriendlyLabel(tagName: string, className: string, hasText: boolean, hasChildren: boolean): string {
  // Check for semantic class names first
  const classes = className.toLowerCase().split(/\s+/);
  if (classes.includes('subtitle')) return 'Subtitle';
  if (classes.includes('title')) return 'Title';
  if (classes.includes('heading')) return 'Heading';
  
  switch (tagName) {
    case 'h1':
      return 'Title';
    case 'h2':
      return 'Heading';
    case 'h3':
    case 'h4':
    case 'h5':
    case 'h6':
      return 'Subheading';
    case 'p':
      return 'Paragraph';
    case 'span':
      return 'Text';
    case 'canvas':
      return 'Chart';
    case 'img':
      return 'Image';
    case 'svg':
      return 'Icon';
    case 'ul':
    case 'ol':
      return 'List';
    case 'li':
      return 'Item';
    case 'table':
      return 'Table';
    case 'tr':
      return 'Row';
    case 'td':
    case 'th':
      return 'Cell';
    case 'a':
      return 'Link';
    case 'button':
      return 'Button';
    case 'div':
      // For divs, use context to determine label
      if (hasText) return 'Text';
      if (hasChildren) return 'Section';
      return 'Block';
    default:
      return 'Block';
  }
}

// Tag badge styling based on tag type
function getTagBadgeStyle(tagName: string, isReadOnly: boolean): string {
  if (isReadOnly) {
    return 'bg-purple-100 text-purple-800';
  }
  
  switch (tagName) {
    case 'h1':
    case 'h2':
    case 'h3':
    case 'h4':
    case 'h5':
    case 'h6':
      return 'bg-blue-100 text-blue-800 font-semibold';
    case 'p':
    case 'span':
      return 'bg-gray-100 text-gray-700';
    case 'img':
    case 'svg':
      return 'bg-green-100 text-green-800';
    default:
      return 'bg-gray-50 text-gray-600';
  }
}

// Truncate text for display
function truncateText(text: string, maxLength = 50): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}

// Inline text editor component
const TextEditor: React.FC<TextEditorProps> = ({ value, onSave, onCancel }) => {
  const [editValue, setEditValue] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const isLongText = value.length > 50;
  
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);
  
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSave(editValue);
    } else if (e.key === 'Escape') {
      onCancel();
    }
  };
  
  const handleBlur = () => {
    onSave(editValue);
  };
  
  const commonProps = {
    value: editValue,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => 
      setEditValue(e.target.value),
    onKeyDown: handleKeyDown,
    onBlur: handleBlur,
    className: 'flex-1 px-2 py-1 text-sm border border-blue-400 rounded focus:outline-none focus:ring-2 focus:ring-blue-500',
  };
  
  if (isLongText) {
    return (
      <textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement>}
        {...commonProps}
        rows={3}
      />
    );
  }
  
  return (
    <input
      ref={inputRef as React.RefObject<HTMLInputElement>}
      type="text"
      {...commonProps}
    />
  );
};

// Single tree node component
const TreeNode: React.FC<TreeNodeProps> = ({
  node,
  depth,
  isExpanded,
  expandedIds,
  onToggleExpand,
  onTextChange,
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const hasChildren = node.children.length > 0;
  const paddingLeft = depth * 16; // 16px per level
  
  // Get friendly label for this node
  const friendlyLabel = getFriendlyLabel(node.tagName, node.className, node.isEditable, hasChildren);
  
  const handleTextClick = () => {
    if (node.isEditable && !node.isReadOnly) {
      setIsEditing(true);
    }
  };
  
  const handleTextSave = (newText: string) => {
    setIsEditing(false);
    if (newText !== node.textContent) {
      onTextChange(node.id, newText);
    }
  };
  
  const handleTextCancel = () => {
    setIsEditing(false);
  };
  
  return (
    <div>
      <div 
        className="flex items-center gap-2 py-1.5 px-2 hover:bg-gray-50 rounded group"
        style={{ paddingLeft: `${paddingLeft + 8}px` }}
      >
        {/* Expand/Collapse button */}
        {hasChildren ? (
          <button
            onClick={() => onToggleExpand(node.id)}
            className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600"
          >
            <FiChevronRight 
              size={14}
              className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            />
          </button>
        ) : (
          <span className="w-4" />
        )}
        
        {/* Friendly label badge */}
        <span className={`px-1.5 py-0.5 text-xs rounded ${getTagBadgeStyle(node.tagName, node.isReadOnly)}`}>
          {friendlyLabel}
        </span>
        
        {/* Read-only lock icon */}
        {node.isReadOnly && (
          <FiLock size={12} className="text-purple-600" />
        )}
        
        {/* Text content or editor */}
        {node.isEditable && !node.isReadOnly && (
          isEditing ? (
            <TextEditor
              value={node.textContent || ''}
              onSave={handleTextSave}
              onCancel={handleTextCancel}
            />
          ) : (
            <span
              onClick={handleTextClick}
              className="flex-1 text-sm text-gray-700 cursor-pointer hover:text-blue-600 hover:underline truncate"
              title={node.textContent || undefined}
            >
              "{truncateText(node.textContent || '')}"
            </span>
          )
        )}
        
        {/* Item count for collapsed containers */}
        {hasChildren && !isExpanded && !node.isEditable && (
          <span className="text-xs text-gray-400">
            • {node.children.length}
          </span>
        )}
      </div>
      
      {/* Render children if expanded */}
      {hasChildren && isExpanded && (
        <div>
          {node.children.map(child => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              isExpanded={expandedIds.has(child.id)}
              expandedIds={expandedIds}
              onToggleExpand={onToggleExpand}
              onTextChange={onTextChange}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// Main tree view component
export const ElementTreeView: React.FC<ElementTreeViewProps> = ({
  nodes,
  expandedIds,
  onToggleExpand,
  onTextChange,
}) => {
  if (nodes.length === 0) {
    return (
      <div className="p-4 text-sm text-gray-500 italic">
        No content found in this slide
      </div>
    );
  }
  
  return (
    <div className="py-2">
      {nodes.map(node => (
        <TreeNode
          key={node.id}
          node={node}
          depth={0}
          isExpanded={expandedIds.has(node.id)}
          expandedIds={expandedIds}
          onToggleExpand={onToggleExpand}
          onTextChange={onTextChange}
        />
      ))}
    </div>
  );
};
