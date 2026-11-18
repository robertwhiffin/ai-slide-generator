// Pseudo-elements, read-only (ruling R8).
//
// What a deck paints with ::before and ::after (square bullets, accent bars,
// timeline dots, step numbers, quote marks) is no element, so the snapshot's
// DOM walk cannot read it; nor is a list item's ::marker ("1.", "4." in a
// reversed list, "•", an image), whose numbering no export may count by hand.
// This module reads every generated ::before, ::after and ::marker from Node,
// through the DevTools protocol (a Playwright CDPSession on the slide's page),
// once the page has settled and just before the snapshot:
//
//   readPseudoElements(page) -> PseudoData (below), handed to the snapshot
//                               evaluation as its argument (snapshot.mjs).
//
// * The box is DOM.getBoxModel's border quad of the pseudo-element node
//   (DOM.getDocument lists each element's pseudoElements). Its box fragments,
//   one per line an inline pseudo-element is laid out on, are
//   DOM.getContentQuads'.
// * The text is what the browser rendered for its `content`: the layout text
//   that DOMSnapshot.captureSnapshot attributes to the pseudo-element node,
//   each inline text box with its own rect. That is Chrome's own evaluation of
//   string escapes, quotes, attr() and counter()/counters() in every counter
//   style, after text-transform and with collapsed white space already left
//   out of the boxes. For a ::marker it is the list's own numbering, start,
//   reversed and value included, in the list's counter style ("1. ", "• ").
//   The layout text itself is read too, in logical order: a right-to-left
//   marker's text boxes are in visual order ("." then "1"), its text is not.
// * The computed style is read by the snapshot in the page, with
//   getComputedStyle(host, '::before'), named properties only.
//
// Nothing is inserted into the page for them. So no deck rule can match
// differently because of the export (a node inserted first in a row would
// shift every :nth-child after it), and page script, which runs in the page's
// realm, cannot reach what the protocol reads. The one write is a
// layout-neutral attribute, PSEUDO_HOST_ATTRIBUTE, set through the protocol on
// each host so the snapshot can tie the data to its element: its value is the
// host's index in PseudoData.hosts. The same attribute on any other element
// (a slide could carry it) is taken off first.
//
// Every loop is bounded by dom_access.mjs's WALK_STEP_LIMIT (depth) and
// COLLECTION_ITEM_LIMIT (breadth), as the page-side reads are; meeting a bound
// is announced on stderr. A read that fails is announced too, and the slide
// then exports without its pseudo-elements; so is every host attribute that
// could not be written or taken off, and every box read that failed, in one
// count line.
//
// Coordinates. DOM.getBoxModel and DOM.getContentQuads report the viewport's,
// as getBoundingClientRect and Range rects do; DOMSnapshot reports the
// document's. Its rects are moved by the document's scroll offset, so a page
// its slide script scrolled reads as the viewport shows it.
//
// /**
//  * PseudoData = {hosts: Host[], count, truncated}
//  * Host       = {before: Pseudo|null, after: Pseudo|null, marker: Pseudo|null}
//  *              (index = the host's PSEUDO_HOST_ATTRIBUTE value)
//  * Pseudo     = {quad: number[8], fragments: number[8][], pieces: Box[][], text, extent: Rect|null}
//  *   quad       its border box, four corners clockwise from the top left, CSS px;
//  *   fragments  its box fragments as quads, in the browser's order;
//  *   pieces     its text, one piece per layout text object in layout order,
//  *              each piece its inline text boxes in order;
//  *   text       its layout text objects' text, concatenated in layout order:
//  *              the text in logical order, white space as laid out ("1. ");
//  *   extent     the union of every layout object it generates ({x, y, w, h}): an
//  *              image it generates may be taller than the line it sits in;
//  * Box        = {text, x, y, w, h}: the text one box paints and its rect, CSS px.
//  */

import { COLLECTION_ITEM_LIMIT, WALK_STEP_LIMIT } from './dom_access.mjs';

export const PSEUDO_HOST_ATTRIBUTE = 'data-tellr-pseudo-host';

// A list item's marker is the protocol's pseudoType "marker": a node with no
// children, listed only when the item has one (not for list-style-type: none,
// nor for ::marker { content: none }).
const PSEUDO_TYPES = ['before', 'after', 'marker'];
const ELEMENT_NODE = 1;
// A layout text object is the pseudo-element node's own, or a child's:
// generated content is a shallow subtree, far shallower than this.
const PSEUDO_TEXT_DEPTH_LIMIT = 16;
// The protocol answers in order; the box reads of a slide are sent this many
// at a time, so a page full of pseudo-elements never has them all in flight.
const PROTOCOL_BATCH = 256;
const NO_PSEUDO_ELEMENTS = { hosts: [], count: 0, truncated: false };

function reportTruncation(what) {
  console.error(
    `[html2pptx] collection truncated at ${what} in the pseudo-element read: content past that ` +
    'point is NOT in the exported deck. This bound is unreachable for real slide content, so ' +
    'meeting it means the document presented an implausible collection.'
  );
}

// Each item of `list` through `send`, PROTOCOL_BATCH at a time, in order. A
// failed read is null.
async function sendInBatches(list, send) {
  const results = [];
  for (let start = 0; start < list.length; start += PROTOCOL_BATCH) {
    const batch = list.slice(start, start + PROTOCOL_BATCH).map((item) => send(item).catch(() => null));
    results.push(...(await Promise.all(batch)));
  }
  return results;
}

function hasHostAttribute(node) {
  const attributes = Array.isArray(node.attributes) ? node.attributes : [];
  const length = Math.min(attributes.length, COLLECTION_ITEM_LIMIT);
  for (let index = 0; index < length; index += 2) {
    if (attributes[index] === PSEUDO_HOST_ATTRIBUTE) return true;
  }
  return false;
}

// The element's generated ::before, ::after and ::marker nodes, or null for
// none. Only generated ones are listed: a pseudo-element whose content is none
// or normal, or whose display is none, has no node, and nor has the marker of
// an item that is no list item or whose list-style-type is none.
function pseudoNodesOf(node) {
  const listed = Array.isArray(node.pseudoElements) ? node.pseudoElements : [];
  const found = { before: null, after: null, marker: null };
  for (let index = 0; index < listed.length && index < WALK_STEP_LIMIT; index++) {
    const type = listed[index] && listed[index].pseudoType;
    if (PSEUDO_TYPES.includes(type) && !found[type]) found[type] = listed[index];
  }
  return found.before || found.after || found.marker ? found : null;
}

// The document's elements that generate a ::before, ::after or ::marker, in
// DOM pre-order, and every element that carries the host attribute already.
function findHosts(root) {
  const hosts = [];
  const marked = [];
  const pending = [{ node: root, depth: 0 }];
  let visited = 0;
  let truncated = false;
  while (pending.length) {
    const next = pending.pop();
    if (++visited > COLLECTION_ITEM_LIMIT) {
      reportTruncation(`${COLLECTION_ITEM_LIMIT} nodes`);
      truncated = true;
      break;
    }
    const node = next.node;
    if (node.nodeType === ELEMENT_NODE) {
      if (hasHostAttribute(node)) marked.push(node.nodeId);
      const pseudo = pseudoNodesOf(node);
      if (pseudo) hosts.push({ nodeId: node.nodeId, before: pseudo.before, after: pseudo.after, marker: pseudo.marker });
    }
    const children = Array.isArray(node.children) ? node.children : [];
    if (!children.length) continue;
    if (next.depth >= WALK_STEP_LIMIT) {
      if (!truncated) reportTruncation(`depth ${WALK_STEP_LIMIT}`);
      truncated = true;
      continue;
    }
    for (let index = Math.min(children.length, COLLECTION_ITEM_LIMIT) - 1; index >= 0; index--) {
      pending.push({ node: children[index], depth: next.depth + 1 });
    }
  }
  return { hosts, marked, truncated };
}

// backendNodeId -> {pieces, text, extent}: what each pseudo-element generates,
// from one DOMSnapshot. Each layout object is owned by the pseudo-element node
// it descends from, within PSEUDO_TEXT_DEPTH_LIMIT. Each inline text box of one
// is a Box of that object's piece, the substring of the layout text it
// paints; the text is the owned layout text objects' own text, in layout
// order, at most COLLECTION_ITEM_LIMIT characters; the extent is the union of
// the owned objects' bounds that have area. Every rect is moved from the
// document's coordinates to the viewport's, by the document's scroll offset.
function generatedContentOf(snapshot, wanted) {
  const content = new Map();
  const documentSnapshot = snapshot && Array.isArray(snapshot.documents) ? snapshot.documents[0] : null;
  if (!documentSnapshot) return content;
  const strings = Array.isArray(snapshot.strings) ? snapshot.strings : [];
  const nodes = documentSnapshot.nodes || {};
  const layout = documentSnapshot.layout || {};
  const textBoxes = documentSnapshot.textBoxes || {};
  const backendIds = Array.isArray(nodes.backendNodeId) ? nodes.backendNodeId : [];
  const parents = Array.isArray(nodes.parentIndex) ? nodes.parentIndex : [];
  const layoutNodes = Array.isArray(layout.nodeIndex) ? layout.nodeIndex : [];
  const layoutBounds = Array.isArray(layout.bounds) ? layout.bounds : [];
  const layoutText = Array.isArray(layout.text) ? layout.text : [];
  const boxLayout = Array.isArray(textBoxes.layoutIndex) ? textBoxes.layoutIndex : [];
  const boxBounds = Array.isArray(textBoxes.bounds) ? textBoxes.bounds : [];
  const boxStart = Array.isArray(textBoxes.start) ? textBoxes.start : [];
  const boxLength = Array.isArray(textBoxes.length) ? textBoxes.length : [];
  const scrollX = Number(documentSnapshot.scrollOffsetX) || 0;
  const scrollY = Number(documentSnapshot.scrollOffsetY) || 0;
  // {x, y, w, h} in the viewport, or null for bounds that are not four finite numbers.
  const viewportRect = (bounds) => {
    if (!Array.isArray(bounds) || bounds.length < 4) return null;
    const rect = { x: Number(bounds[0]) - scrollX, y: Number(bounds[1]) - scrollY, w: Number(bounds[2]), h: Number(bounds[3]) };
    return Number.isFinite(rect.x) && Number.isFinite(rect.y) && rect.w >= 0 && rect.h >= 0 ? rect : null;
  };

  // Snapshot node index -> backendNodeId, for the pseudo-element nodes only.
  const ownerIds = new Map();
  for (let index = 0; index < backendIds.length && index < COLLECTION_ITEM_LIMIT; index++) {
    if (wanted.has(backendIds[index])) ownerIds.set(index, backendIds[index]);
  }
  if (!ownerIds.size) return content;
  const ownerOfLayout = new Map();
  const ownerOf = (layoutIndex) => {
    if (ownerOfLayout.has(layoutIndex)) return ownerOfLayout.get(layoutIndex);
    let node = layoutNodes[layoutIndex];
    let owner = null;
    for (let depth = 0; depth < PSEUDO_TEXT_DEPTH_LIMIT && Number.isInteger(node) && node >= 0; depth++) {
      if (ownerIds.has(node)) {
        owner = ownerIds.get(node);
        break;
      }
      node = parents[node];
    }
    ownerOfLayout.set(layoutIndex, owner);
    return owner;
  };
  const contentOf = (owner) => {
    if (!content.has(owner)) content.set(owner, { pieces: [], text: '', extent: null });
    return content.get(owner);
  };

  // owner -> {parts, length}: its layout text, joined once every object is read.
  const textOf = new Map();
  for (let index = 0; index < layoutNodes.length && index < COLLECTION_ITEM_LIMIT; index++) {
    const owner = ownerOf(index);
    if (owner === null) continue;
    const ownText = strings[layoutText[index]];
    if (typeof ownText === 'string' && ownText) {
      if (!textOf.has(owner)) textOf.set(owner, { parts: [], length: 0 });
      const text = textOf.get(owner);
      if (text.length < COLLECTION_ITEM_LIMIT) {
        text.parts.push(ownText);
        text.length += ownText.length;
      }
    }
    const rect = viewportRect(layoutBounds[index]);
    if (!rect || !(rect.w > 0 && rect.h > 0)) continue;
    const generated = contentOf(owner);
    const extent = generated.extent;
    if (!extent) {
      generated.extent = rect;
      continue;
    }
    const right = Math.max(extent.x + extent.w, rect.x + rect.w);
    const bottom = Math.max(extent.y + extent.h, rect.y + rect.h);
    extent.x = Math.min(extent.x, rect.x);
    extent.y = Math.min(extent.y, rect.y);
    extent.w = right - extent.x;
    extent.h = bottom - extent.y;
  }

  const pieceOfLayout = new Map();
  for (let index = 0; index < boxLayout.length && index < COLLECTION_ITEM_LIMIT; index++) {
    const layoutIndex = boxLayout[index];
    const owner = ownerOf(layoutIndex);
    if (owner === null) continue;
    const text = strings[layoutText[layoutIndex]];
    const rect = viewportRect(boxBounds[index]);
    if (typeof text !== 'string' || !rect) continue;
    const start = Number(boxStart[index]);
    const length = Number(boxLength[index]);
    if (!(Number.isInteger(start) && Number.isInteger(length) && start >= 0 && length > 0)) continue;
    let piece = pieceOfLayout.get(layoutIndex);
    if (!piece) {
      piece = [];
      pieceOfLayout.set(layoutIndex, piece);
      contentOf(owner).pieces.push(piece);
    }
    piece.push({ text: text.slice(start, start + length), x: rect.x, y: rect.y, w: rect.w, h: rect.h });
  }
  for (const [owner, text] of textOf) {
    contentOf(owner).text = text.parts.join('').slice(0, COLLECTION_ITEM_LIMIT);
  }
  return content;
}

function isQuad(quad) {
  return Array.isArray(quad) && quad.length === 8 && quad.every((value) => Number.isFinite(value));
}

async function readThrough(session) {
  const { root } = await session.send('DOM.getDocument', { depth: -1 });
  const found = findHosts(root);
  const pseudoNodes = [];
  for (const host of found.hosts) {
    for (const type of PSEUDO_TYPES) {
      if (host[type]) pseudoNodes.push(host[type]);
    }
  }
  const wanted = new Set(pseudoNodes.map((node) => node.backendNodeId));
  const snapshot = pseudoNodes.length
    ? await session.send('DOMSnapshot.captureSnapshot', { computedStyles: [] })
    : null;
  const generated = snapshot ? generatedContentOf(snapshot, wanted) : new Map();

  // A pseudo-element whose box cannot be read is not drawn; one whose
  // fragments cannot be read is drawn without them. Both are counted.
  const boxes = await sendInBatches(pseudoNodes, (node) => session.send('DOM.getBoxModel', { nodeId: node.nodeId }));
  const quads = await sendInBatches(pseudoNodes, (node) => session.send('DOM.getContentQuads', { nodeId: node.nodeId }));
  const readOf = new Map();
  let unread = 0;
  pseudoNodes.forEach((node, index) => {
    const quad = boxes[index] && boxes[index].model ? boxes[index].model.border : null;
    if (!isQuad(quad) || !quads[index]) unread += 1;
    if (!isQuad(quad)) return;
    const listed = quads[index] && Array.isArray(quads[index].quads) ? quads[index].quads : [];
    const content = generated.get(node.backendNodeId) || { pieces: [], text: '', extent: null };
    readOf.set(node, {
      quad,
      fragments: listed.slice(0, WALK_STEP_LIMIT).filter(isQuad),
      pieces: content.pieces,
      text: content.text,
      extent: content.extent,
    });
  });

  const hosts = [];
  const hostIds = [];
  let count = 0;
  for (const host of found.hosts) {
    const read = {};
    let any = 0;
    for (const type of PSEUDO_TYPES) {
      read[type] = host[type] ? readOf.get(host[type]) || null : null;
      if (read[type]) any += 1;
    }
    if (!any) continue;
    hosts.push({ before: read.before, after: read.after, marker: read.marker });
    hostIds.push(host.nodeId);
    count += any;
  }

  // The host attributes, written once everything is read: stale ones off,
  // then one per host. A stale one left on can claim a real host's pseudo-elements.
  const hostSet = new Set(hostIds);
  const removed = await sendInBatches(found.marked.filter((nodeId) => !hostSet.has(nodeId)), (nodeId) =>
    session.send('DOM.removeAttribute', { nodeId, name: PSEUDO_HOST_ATTRIBUTE }).then(() => true));
  const written = await sendInBatches(hostIds.map((nodeId, index) => ({ nodeId, index })), (host) =>
    session.send('DOM.setAttributeValue', { nodeId: host.nodeId, name: PSEUDO_HOST_ATTRIBUTE, value: String(host.index) })
      .then(() => true));
  reportFailures({
    unread,
    unremoved: removed.filter((result) => result !== true).length,
    unmarked: written.filter((result) => result !== true).length,
  });
  return { hosts, count, truncated: found.truncated };
}

// One count line for what the read could not do; nothing when it did it all.
function reportFailures({ unread, unremoved, unmarked }) {
  if (!unread && !unremoved && !unmarked) return;
  console.error(
    `[html2pptx] pseudo-elements: ${unmarked} host(s) could not be marked, ` +
    `${unremoved} stale host attribute(s) could not be taken off and ${unread} box read(s) failed; ` +
    'the ::before, ::after and ::marker they hold may be missing from the exported deck or drawn on the wrong element'
  );
}

// readPseudoElements(page) -> PseudoData. Never throws: a page whose
// pseudo-elements cannot be read exports without them, and says so.
export async function readPseudoElements(page) {
  let session = null;
  try {
    session = await page.context().newCDPSession(page);
    return await readThrough(session);
  } catch (error) {
    const message = String((error && error.message) || error).split('\n')[0];
    console.error(`[html2pptx] pseudo-elements could not be read (${message}); this slide exports without its ::before, ::after and list markers`);
    return NO_PSEUDO_ELEMENTS;
  } finally {
    if (session) await session.detach().catch(() => {});
  }
}
