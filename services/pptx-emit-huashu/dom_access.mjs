// Pristine-realm DOM access and bounded collection reads, shared by every
// page-side pass the sidecar evaluates (preprocess.mjs, snapshot.mjs and the
// settle reads in render_slide.cjs).
//
// Why this exists. SLIDE_CSP (src/utils/html_safety.py) carries script-src
// 'unsafe-inline', so inline script in an uploaded slide runs in the export page
// at load, before any pass is evaluated. Every DOM accessor, lookup and
// collection iterator a pass would naturally use (children, firstElementChild,
// querySelectorAll, NodeList.prototype.forEach, [Symbol.iterator]) is a
// CONFIGURABLE property page script can replace: with a decoy, with a lie about
// the tree, or with something that never returns. So the passes read the tree
// through accessors captured from a src-less iframe's realm, which no page script
// has run in, and consume collections by walking the sibling chain or indexing
// under a bound. Correctness in a hostile realm is best effort (the means of
// reaching a pristine realm are themselves replaceable); TERMINATION is not,
// because every read is bounded by WALK_STEP_LIMIT or COLLECTION_ITEM_LIMIT.
// Reaching a bound is announced on stderr, never silent: the items past it are
// missing from the exported deck.
//
// Composition contract. DOM_ACCESS_SOURCE is pasted into the composing pass's
// own IIFE, after that pass declares the prefix its collection-loss line carries:
//
//   (async function () {
//     const DOM_ACCESS_LOG_PREFIX = '[preprocess]';   // or '[html2pptx]'
//     ${DOM_ACCESS_SOURCE}
//     ...the pass...
//   })()
//
// Both prefixes are routed to stderr by the page console handler, which is the
// only stream pptx_from_html_huashu.py echoes into the app log. The guard at the
// top fails the pass immediately when the prefix is missing, rather than at the
// first bound that is met.
//
// The two bounds are exported as well, for Node-side readers of the same page
// (pseudo.mjs reads its pseudo-elements through the DevTools protocol), so a
// tree read from either side stops at the same depth and breadth.

// Hard stop on any descent: eight times Chromium's parsed-depth ceiling (512), so only a lying realm reaches it.
export const WALK_STEP_LIMIT = 4096;

// The same guarantee for breadth: a slide holding a million nodes could not render at 1280x720.
export const COLLECTION_ITEM_LIMIT = 1000000;

export const DOM_ACCESS_SOURCE = `
  if (typeof DOM_ACCESS_LOG_PREFIX !== 'string') {
    throw new Error('DOM_ACCESS_SOURCE needs DOM_ACCESS_LOG_PREFIX declared before it');
  }

  const WALK_STEP_LIMIT = ${WALK_STEP_LIMIT};
  const COLLECTION_ITEM_LIMIT = ${COLLECTION_ITEM_LIMIT};

  // DOM reads through primitives from a src-less iframe's realm, which no page script has run in.
  function capturePristineDomAccess() {
    let frame = null;
    let removeFrame = null;
    try {
      frame = document.createElement('iframe');
      frame.style.display = 'none';
      // documentElement, not body: nothing here may perturb body's child list.
      document.documentElement.appendChild(frame);
      const realm = frame.contentWindow;
      // A replaced createElement/contentWindow could hand back THIS realm; distinct intrinsics is the check.
      if (!realm || realm === window || realm.Element === window.Element) return null;
      // The frame is taken off through its own realm: page script can make the
      // page's remove do nothing, and a frame left after body restyles the page.
      removeFrame = realm.Element.prototype.remove;
      const describe = realm.Object.getOwnPropertyDescriptor;
      const firstChild = describe(realm.Element.prototype, 'firstElementChild');
      const nextSibling = describe(realm.Element.prototype, 'nextElementSibling');
      const tag = describe(realm.Element.prototype, 'tagName');
      const matches = realm.Element.prototype.matches;
      // Node-level siblings for child NODE lists (text and comments included), and NodeList's own length.
      const firstNode = describe(realm.Node.prototype, 'firstChild');
      const nextNode = describe(realm.Node.prototype, 'nextSibling');
      const listLength = describe(realm.NodeList.prototype, 'length');
      // What a child node is, and a text node's characters, for passes that read text.
      const typeOfNode = describe(realm.Node.prototype, 'nodeType');
      const characterData = describe(realm.CharacterData.prototype, 'data');
      // An HTML element's rendered text, as a screen reader and the text-loss oracle read it.
      const renderedText = describe(realm.HTMLElement.prototype, 'innerText');
      // Document's and Element's lookups are DISTINCT function objects, so both are captured.
      const docQuery = realm.Document.prototype.querySelector;
      const docQueryAll = realm.Document.prototype.querySelectorAll;
      const elQuery = realm.Element.prototype.querySelector;
      const elQueryAll = realm.Element.prototype.querySelectorAll;
      // An element's box fragments. Even through the pristine method the DOMRectList and its DOMRects
      // are the page realm's objects, whose length, item and rect getters page script can replace, so those are captured too.
      const clientRects = realm.Element.prototype.getClientRects;
      const rectListLength = describe(realm.DOMRectList.prototype, 'length');
      const rectListItem = realm.DOMRectList.prototype.item;
      const rectLeft = describe(realm.DOMRectReadOnly.prototype, 'left');
      const rectTop = describe(realm.DOMRectReadOnly.prototype, 'top');
      const rectWidth = describe(realm.DOMRectReadOnly.prototype, 'width');
      const rectHeight = describe(realm.DOMRectReadOnly.prototype, 'height');
      // How the snapshot names its capture targets, once it has read everything (snapshot.mjs nameCaptureTargets).
      const setAttribute = realm.Element.prototype.setAttribute;
      const removeAttribute = realm.Element.prototype.removeAttribute;
      // How the snapshot reads the attribute the DevTools protocol put on each pseudo-element host (snapshot.mjs readPseudoHosts).
      const getAttribute = realm.Element.prototype.getAttribute;
      // How a pass adds the nodes it measures with and takes them off again
      // (snapshot_text.mjs measureProbes): page script can take away the page
      // realm's own, and a node left in the page restyles what the pass reads.
      // Document's methods are called with this realm's document as receiver.
      const createElement = realm.Document.prototype.createElement;
      const createTextNode = realm.Document.prototype.createTextNode;
      const appendChild = realm.Node.prototype.appendChild;
      const removeNode = realm.Element.prototype.remove;
      if (typeof firstChild.get !== 'function' ||
          typeof nextSibling.get !== 'function' ||
          typeof tag.get !== 'function' ||
          typeof matches !== 'function' ||
          typeof firstNode.get !== 'function' ||
          typeof nextNode.get !== 'function' ||
          typeof listLength.get !== 'function' ||
          typeof typeOfNode.get !== 'function' ||
          typeof characterData.get !== 'function' ||
          typeof renderedText.get !== 'function' ||
          typeof docQuery !== 'function' ||
          typeof docQueryAll !== 'function' ||
          typeof elQuery !== 'function' ||
          typeof elQueryAll !== 'function' ||
          typeof clientRects !== 'function' ||
          typeof rectListLength.get !== 'function' ||
          typeof rectListItem !== 'function' ||
          typeof rectLeft.get !== 'function' ||
          typeof rectTop.get !== 'function' ||
          typeof rectWidth.get !== 'function' ||
          typeof rectHeight.get !== 'function' ||
          typeof setAttribute !== 'function' ||
          typeof removeAttribute !== 'function' ||
          typeof getAttribute !== 'function' ||
          typeof createElement !== 'function' ||
          typeof createTextNode !== 'function' ||
          typeof appendChild !== 'function' ||
          typeof removeNode !== 'function') return null;
      return {
        pristine: true,
        firstElementChild: (el) => firstChild.get.call(el),
        nextElementSibling: (el) => nextSibling.get.call(el),
        tagName: (el) => tag.get.call(el),
        matches: (el, selector) => matches.call(el, selector),
        firstChild: (node) => firstNode.get.call(node),
        nextSibling: (node) => nextNode.get.call(node),
        nodeListLength: (list) => listLength.get.call(list),
        nodeType: (node) => typeOfNode.get.call(node),
        textData: (node) => characterData.get.call(node),
        // Throws for an element that is not HTML (an <svg>): callers guard it.
        innerText: (el) => renderedText.get.call(el),
        // The receiver stays this realm's document; a native lookup with an explicit receiver works across realms.
        documentQuerySelector: (selector) => docQuery.call(document, selector),
        documentQuerySelectorAll: (selector) => docQueryAll.call(document, selector),
        elementQuerySelector: (el, selector) => elQuery.call(el, selector),
        elementQuerySelectorAll: (el, selector) => elQueryAll.call(el, selector),
        clientRects: (el) => clientRects.call(el),
        rectListLength: (list) => rectListLength.get.call(list),
        rectAt: (list, index) => rectListItem.call(list, index),
        rectBounds: (rect) => ({
          left: rectLeft.get.call(rect),
          top: rectTop.get.call(rect),
          width: rectWidth.get.call(rect),
          height: rectHeight.get.call(rect),
        }),
        setAttribute: (el, name, value) => setAttribute.call(el, name, value),
        removeAttribute: (el, name) => removeAttribute.call(el, name),
        getAttribute: (el, name) => getAttribute.call(el, name),
        createElement: (name) => createElement.call(document, name),
        createTextNode: (text) => createTextNode.call(document, text),
        appendChild: (parent, child) => appendChild.call(parent, child),
        remove: (el) => removeNode.call(el),
      };
    } catch (e) {
      return null;
    } finally {
      // The captured accessors keep working once the frame is gone, so the export DOM never contains it.
      if (frame) {
        try {
          if (typeof removeFrame === 'function') removeFrame.call(frame);
          else frame.remove();
        } catch (e) { /* already detached — nothing to undo */ }
      }
    }
  }

  // Fallback when the capture could not be trusted: correct in a clean realm, bounded in a hostile one.
  const OWN_DOM_ACCESS = {
    pristine: false,
    firstElementChild: (el) => el.firstElementChild,
    nextElementSibling: (el) => el.nextElementSibling,
    tagName: (el) => el.tagName,
    matches: (el, selector) => el.matches(selector),
    firstChild: (node) => node.firstChild,
    nextSibling: (node) => node.nextSibling,
    nodeListLength: (list) => list.length,
    nodeType: (node) => node.nodeType,
    textData: (node) => node.data,
    innerText: (el) => el.innerText,
    documentQuerySelector: (selector) => document.querySelector(selector),
    documentQuerySelectorAll: (selector) => document.querySelectorAll(selector),
    elementQuerySelector: (el, selector) => el.querySelector(selector),
    elementQuerySelectorAll: (el, selector) => el.querySelectorAll(selector),
    clientRects: (el) => el.getClientRects(),
    rectListLength: (list) => list.length,
    rectAt: (list, index) => list[index],
    rectBounds: (rect) => ({ left: rect.left, top: rect.top, width: rect.width, height: rect.height }),
    setAttribute: (el, name, value) => el.setAttribute(name, value),
    removeAttribute: (el, name) => el.removeAttribute(name),
    getAttribute: (el, name) => el.getAttribute(name),
    createElement: (name) => document.createElement(name),
    createTextNode: (text) => document.createTextNode(text),
    appendChild: (parent, child) => parent.appendChild(child),
    remove: (el) => el.remove(),
  };

  // One capture per pass, made on first use, so no pass re-enters the iframe per call.
  let domAccessCache = null;
  function domAccess() {
    if (!domAccessCache) {
      domAccessCache = capturePristineDomAccess() || OWN_DOM_ACCESS;
    }
    return domAccessCache;
  }

  // A bound that is reached is a bug, so it is announced on stderr, once per pass, never per item.
  let collectionLossReported = false;
  function reportCollectionLoss(prefix, what, where) {
    if (collectionLossReported) return;
    collectionLossReported = true;
    console.warn(
      prefix + ' collection ' + what + ' in ' + where + ': content past that ' +
      'point is NOT in the exported deck. This bound is unreachable for real slide ' +
      'content, so meeting it means the document presented an implausible ' +
      'collection or the realm is lying about one.'
    );
  }

  // Every child NODE, in order, over the sibling chain: the Array.from(node.childNodes) replacement.
  function childNodesOf(node) {
    const dom = domAccess();
    const nodes = [];
    let child = dom.firstChild(node);
    while (child && nodes.length < COLLECTION_ITEM_LIMIT) {
      nodes.push(child);
      child = dom.nextSibling(child);
    }
    // A surviving child is exactly the bound being met: the loop's other exit is a falsy one.
    if (child) reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' items', 'childNodesOf');
    return nodes;
  }

  // Element children only: the Array.from(element.children) replacement.
  function elementChildrenOf(element) {
    const dom = domAccess();
    const elements = [];
    let child = dom.firstElementChild(element);
    while (child && elements.length < COLLECTION_ITEM_LIMIT) {
      elements.push(child);
      child = dom.nextElementSibling(child);
    }
    if (child) reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' items', 'elementChildrenOf');
    return elements;
  }

  // A static NodeList has no sibling chain, so it is an index loop over the pristine length.
  function nodeListToArray(list) {
    const reported = domAccess().nodeListLength(list);
    const length = Math.min(reported, COLLECTION_ITEM_LIMIT);
    const nodes = [];
    for (let index = 0; index < length; index++) nodes.push(list[index]);
    if (reported > COLLECTION_ITEM_LIMIT) {
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'truncated at ' + COLLECTION_ITEM_LIMIT + ' of ' + reported + ' items', 'nodeListToArray');
    } else if (!(reported >= 0)) {
      // A length that is not a number empties the loop: terminating, but content loss all the same.
      reportCollectionLoss(DOM_ACCESS_LOG_PREFIX, 'dropped entirely, length read as ' + String(reported), 'nodeListToArray');
    }
    return nodes;
  }

  // Document-scoped lookups through the pristine copy, returned as a plain Array iterated with Array.prototype.
  function queryAll(selector) {
    return nodeListToArray(domAccess().documentQuerySelectorAll(selector));
  }

  // The same, scoped to an element: a DISTINCT function object from the document's.
  function queryAllWithin(element, selector) {
    return nodeListToArray(domAccess().elementQuerySelectorAll(element, selector));
  }

  function queryOne(selector) {
    return domAccess().documentQuerySelector(selector);
  }
`;
