import type { EditableNode } from './visualEditor.types';

/**
 * Parse slide HTML into an editable tree structure.
 * Works with any HTML structure regardless of class names.
 */
export function buildEditableTree(html: string): EditableNode[] {
  const parser = new DOMParser();
  const doc = parser.parseFromString(`<div id="__root__">${html}</div>`, 'text/html');
  const root = doc.getElementById('__root__');
  
  if (!root || !root.firstElementChild) {
    return [];
  }
  
  return [parseElement(root.firstElementChild, '0')];
}

function parseElement(el: Element, pathId: string): EditableNode {
  const tagName = el.tagName.toLowerCase();
  const className = el.getAttribute('class') || '';
  const isReadOnly = ['canvas', 'script', 'style', 'svg', 'img'].includes(tagName);
  
  // Get direct text content (text nodes that are direct children, not nested)
  const directText = Array.from(el.childNodes)
    .filter(n => n.nodeType === Node.TEXT_NODE)
    .map(n => n.textContent?.trim())
    .filter(Boolean)
    .join(' ');
  
  const children = Array.from(el.children)
    .map((child, i) => parseElement(child, `${pathId}.${i}`))
    .filter(c => !['script', 'style', 'br'].includes(c.tagName)); // Filter hidden/empty elements
  
  return {
    id: pathId,
    tagName,
    className,
    textContent: directText || null,
    isEditable: !!directText && !isReadOnly,
    isReadOnly,
    children,
    hasTextChildren: children.some(c => c.isEditable || c.hasTextChildren),
  };
}

/**
 * Convert node ID path string to array of indices.
 * Example: "0.2.1" -> [0, 2, 1]
 */
export function getNodePath(nodeId: string): number[] {
  return nodeId.split('.').map(Number);
}

/**
 * Apply a text change to the HTML at the specified node path.
 * Preserves all HTML structure, attributes, and styling.
 */
export function applyTextChange(
  html: string,
  nodeId: string,
  newText: string
): string {
  const parser = new DOMParser();
  const doc = parser.parseFromString(`<div id="__root__">${html}</div>`, 'text/html');
  const root = doc.getElementById('__root__');
  
  if (!root || !root.firstElementChild) {
    return html;
  }
  
  const path = getNodePath(nodeId);
  let element: Element | null = root.firstElementChild;
  
  // Navigate to the target element using the path
  // Skip the first index (0) as it represents the root slide element
  for (let i = 1; i < path.length && element; i++) {
    const childIndex = path[i];
    const childElements: Element[] = Array.from(element.children);
    element = childElements[childIndex] || null;
  }
  
  if (!element) {
    console.warn(`Could not find element at path: ${nodeId}`);
    return html;
  }
  
  // Replace direct text nodes while preserving child elements
  // Clear existing text nodes
  Array.from(element.childNodes)
    .filter(n => n.nodeType === Node.TEXT_NODE)
    .forEach(n => n.remove());
  
  // Add new text as first child (before any element children)
  if (newText.trim()) {
    const textNode = doc.createTextNode(newText);
    if (element.firstChild) {
      element.insertBefore(textNode, element.firstChild);
    } else {
      element.appendChild(textNode);
    }
  }
  
  // Return the inner HTML of root (excludes the wrapper div)
  return root.innerHTML;
}

/**
 * Build a complete HTML document for preview iframe.
 */
export function buildPreviewHtml(
  slideHtml: string,
  css: string,
  externalScripts: string[],
  slideScripts?: string
): string {
  return `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${externalScripts.map(src => `<script src="${src}"></script>`).join('\n  ')}
  <style>${css}</style>
</head>
<body>
  ${slideHtml}
  ${slideScripts ? `<script>${slideScripts}</script>` : ''}
</body>
</html>
  `.trim();
}

/**
 * Get the default expanded IDs for a tree (first 2 levels)
 */
export function getDefaultExpandedIds(nodes: EditableNode[], maxDepth = 2): Set<string> {
  const expandedIds = new Set<string>();
  
  function traverse(node: EditableNode, depth: number) {
    if (depth < maxDepth && node.children.length > 0) {
      expandedIds.add(node.id);
      node.children.forEach(child => traverse(child, depth + 1));
    }
  }
  
  nodes.forEach(node => traverse(node, 0));
  return expandedIds;
}

