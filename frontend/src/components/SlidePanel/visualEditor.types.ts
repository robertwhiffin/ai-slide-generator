export interface EditableNode {
  id: string;                    // Unique path-based ID (e.g., "0.2.1")
  tagName: string;               // HTML tag (h1, div, p, span, etc.)
  className: string;             // CSS classes for semantic labeling
  textContent: string | null;    // Direct text content (null if only children)
  isEditable: boolean;           // True if has direct text to edit
  isReadOnly: boolean;           // True for canvas, script, style
  children: EditableNode[];      // Nested elements
  hasTextChildren: boolean;      // True if any descendant has text
}

export interface TreeState {
  nodes: EditableNode[];
  expandedIds: Set<string>;
}

