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
// Reaching a bound is announced, never silent: the items past it are missing
// from the exported deck.
//
// The engine's diagnostics. What a pass says about the slide (a bound met, a
// slide with no root, a read the page made fail) reaches the app's log, whose
// readers must learn of content leaving the deck. The page's console is no way
// to say it: slide script can replace it (a console.warn that does nothing)
// and write to it (a line with the engine's prefix), and what a page logs is
// counted, not logged, without the debug text (render_slide.cjs
// forwardConsole). So a pass says it with diagnose(key, ...), the key one of
// the engine's own wordings (model_check.cjs DIAGNOSTIC_LINES and
// DIAGNOSTIC_PARTS, which hold their text), each argument a part's key, a
// number it counted, or a page's text (diagnosticPageText); diagnosticTokens
// builds a part the caller names before it says the line. What it says is
// collected in the pass's own closure, a string built with nothing the page's
// realm can replace (string concatenation, typeof, comparison and a string's
// own length and characters: no Array, String or JSON built-in, no console),
// and returned with the pass's result, passResult(value) ->
// {value, diagnostics, diagnosticsOver}, which Node reads through the
// DevTools protocol (render_slide.cjs evaluatePass), checks against the
// engine's wordings and logs with the pass's prefix. At most
// DIAGNOSTICS_PER_PASS a pass; the rest are counted. Encoding: each entry,
// and each token of an entry (a key, a number as JavaScript writes it, a
// page's text as its length, then at most PAGE_TEXT_LIMIT of its characters),
// is written after its length and a colon.
//
// Composition contract. DOM_ACCESS_SOURCE is pasted into the composing pass's
// own IIFE, which returns what the pass read through passResult:
//
//   (function () {
//     ${DOM_ACCESS_SOURCE}
//     ...the pass...
//     return passResult(value);
//   })()
//
// The two bounds are exported as well, for Node-side readers of the same page
// (pseudo.mjs reads its pseudo-elements through the DevTools protocol), so a
// tree read from either side stops at the same depth and breadth.

import { DIAGNOSTICS_PER_PASS, PAGE_TEXT_LIMIT } from './log_line.cjs';

// Hard stop on any descent: eight times Chromium's parsed-depth ceiling (512), so only a lying realm reaches it.
export const WALK_STEP_LIMIT = 4096;

// The same guarantee for breadth: a slide holding a million nodes could not render at 1280x720.
export const COLLECTION_ITEM_LIMIT = 1000000;

export const DOM_ACCESS_SOURCE = `
  const WALK_STEP_LIMIT = ${WALK_STEP_LIMIT};
  const COLLECTION_ITEM_LIMIT = ${COLLECTION_ITEM_LIMIT};

  // ─── the engine's diagnostics ────────────────────────────────────────
  const DIAGNOSTICS_PER_PASS = ${DIAGNOSTICS_PER_PASS};
  const DIAGNOSTIC_PAGE_TEXT_LIMIT = ${PAGE_TEXT_LIMIT};
  let diagnosticStream = '';
  let diagnosticsKept = 0;
  let diagnosticsOver = 0;

  function lengthPrefixed(text) {
    return text.length + ':' + text;
  }

  // A value of the page's as text, through its own conversion, which may throw.
  function pageString(value) {
    if (typeof value === 'string') return value;
    try {
      return '' + value;
    } catch (e) {
      return '';
    }
  }

  // A number the page side read, which a lying realm can make anything: NaN
  // for what is no number.
  function pageNumber(value) {
    return typeof value === 'number' ? value : NaN;
  }

  // The message of what a page's read threw, which may be the page's own
  // throw and its message a getter of the page's.
  function thrownMessage(error) {
    try {
      return error && error.message;
    } catch (e) {
      return '';
    }
  }

  // A page's text for a diagnostic: its length, and its first
  // DIAGNOSTIC_PAGE_TEXT_LIMIT characters.
  function diagnosticPageText(value) {
    const text = pageString(value);
    let kept = '';
    for (let index = 0; index < text.length && index < DIAGNOSTIC_PAGE_TEXT_LIMIT; index++) kept = kept + text[index];
    return { diagnosticPageText: kept, length: text.length };
  }

  function diagnosticToken(value) {
    if (typeof value === 'string') return lengthPrefixed(value);
    if (typeof value === 'number') return lengthPrefixed('' + value);
    if (value !== null && typeof value === 'object') {
      if (typeof value.diagnosticTokens === 'string') return value.diagnosticTokens;
      if (typeof value.diagnosticPageText === 'string') {
        return lengthPrefixed('' + value.length) + lengthPrefixed(value.diagnosticPageText);
      }
    }
    return lengthPrefixed('');
  }

  // A part's key and what its slots take, as one argument of diagnose. Its
  // arguments are read by index: a spread or for...of would iterate through
  // the page's Array.prototype.
  function diagnosticTokens() {
    let tokens = '';
    for (let index = 0; index < arguments.length; index++) tokens = tokens + diagnosticToken(arguments[index]);
    return { diagnosticTokens: tokens };
  }

  function diagnose() {
    if (diagnosticsKept >= DIAGNOSTICS_PER_PASS) {
      diagnosticsOver += 1;
      return;
    }
    let tokens = '';
    for (let index = 0; index < arguments.length; index++) tokens = tokens + diagnosticToken(arguments[index]);
    diagnosticStream = diagnosticStream + lengthPrefixed(tokens);
    diagnosticsKept += 1;
  }

  function passResult(value) {
    return { value: value, diagnostics: diagnosticStream, diagnosticsOver: diagnosticsOver };
  }

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
      // Document's methods are called with the page's own document as receiver,
      // so what they make belongs to the page, which the pass reads.
      const createElement = realm.Document.prototype.createElement;
      const createTextNode = realm.Document.prototype.createTextNode;
      const appendChild = realm.Node.prototype.appendChild;
      const removeNode = realm.Element.prototype.remove;
      // How many grid rows and columns a table cell spans, and how many columns
      // a <col> or <colgroup> spans, as the HTML table model reads them
      // (snapshot_table.mjs): the attribute values parsed and clamped by the browser.
      const cellRowSpan = describe(realm.HTMLTableCellElement.prototype, 'rowSpan');
      const cellColSpan = describe(realm.HTMLTableCellElement.prototype, 'colSpan');
      const columnSpan = describe(realm.HTMLTableColElement.prototype, 'span');
      const fonts = captureFontAccess(realm, describe);
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
          typeof removeNode !== 'function' ||
          typeof cellRowSpan.get !== 'function' ||
          typeof cellColSpan.get !== 'function' ||
          typeof columnSpan.get !== 'function') return null;
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
        // The receiver is the page's own document, not the pristine realm's; a native lookup with an explicit receiver works across realms.
        documentQuerySelector: (selector) => docQuery.call(document, selector),
        documentQuerySelectorAll: (selector) => docQueryAll.call(document, selector),
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
        // Throw for an element that is not a table cell, or not a <col> or <colgroup>: callers check the tag first.
        rowSpan: (cell) => cellRowSpan.get.call(cell),
        colSpan: (cell) => cellColSpan.get.call(cell),
        columnSpan: (column) => columnSpan.get.call(column),
        fontsReady: fonts.fontsReady,
        loadingFontFaces: fonts.loadingFontFaces,
        addFontFace: fonts.addFontFace,
        deleteFontFace: fonts.deleteFontFace,
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

  // The document's font faces, each one's load status and the promise that
  // settles once none is loading (render_slide.cjs pageFontsSettled), and how a
  // pass adds a face of its own for one probe and deletes it again
  // (snapshot_text_metrics.mjs splitFallbackRuns), from the pristine realm when
  // it has them all, else the page's own (OWN_DOM_ACCESS): apart from the rest,
  // because not every Chromium exposes FontFaceSet as a global (the 147
  // headless shell does not), so its prototype is taken from the pristine
  // document's own font set, and a browser without one must not cost the other
  // reads their pristine accessors. A face of a font's bytes loads at once, so
  // addFontFace gives back the face it added, or null where it did not load; a
  // face the pristine realm made works in the page's document, its frame gone.
  function captureFontAccess(realm, describe) {
    try {
      const documentFonts = describe(realm.Document.prototype, 'fonts');
      const fontSet = documentFonts && typeof documentFonts.get === 'function'
        ? documentFonts.get.call(realm.document)
        : null;
      const fontSetPrototype = fontSet ? realm.Object.getPrototypeOf(fontSet) : null;
      const fontSetReady = fontSetPrototype ? describe(fontSetPrototype, 'ready') : null;
      const fontSetForEach = fontSetPrototype ? fontSetPrototype.forEach : null;
      const fontFaceStatus = realm.FontFace ? describe(realm.FontFace.prototype, 'status') : null;
      const FontFaceOfRealm = realm.FontFace;
      const BytesOfRealm = realm.Uint8Array;
      const fontSetAdd = fontSetPrototype ? fontSetPrototype.add : null;
      const fontSetDelete = fontSetPrototype ? fontSetPrototype.delete : null;
      if (!fontSetReady || typeof fontSetReady.get !== 'function' ||
          typeof fontSetForEach !== 'function' ||
          !fontFaceStatus || typeof fontFaceStatus.get !== 'function' ||
          typeof FontFaceOfRealm !== 'function' || typeof BytesOfRealm !== 'function' ||
          typeof fontSetAdd !== 'function' || typeof fontSetDelete !== 'function') {
        return OWN_DOM_ACCESS;
      }
      return {
        fontsReady: () => fontSetReady.get.call(documentFonts.get.call(document)),
        // The set's own forEach visits each face it holds once, so the count needs no bound.
        loadingFontFaces: () => {
          let loading = 0;
          fontSetForEach.call(documentFonts.get.call(document), (face) => {
            if (fontFaceStatus.get.call(face) === 'loading') loading += 1;
          });
          return loading;
        },
        addFontFace: (family, bytes) => {
          const face = new FontFaceOfRealm(family, new BytesOfRealm(bytes));
          if (fontFaceStatus.get.call(face) !== 'loaded') return null;
          fontSetAdd.call(documentFonts.get.call(document), face);
          return face;
        },
        deleteFontFace: (face) => {
          fontSetDelete.call(documentFonts.get.call(document), face);
        },
      };
    } catch (e) {
      return OWN_DOM_ACCESS;
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
    rowSpan: (cell) => cell.rowSpan,
    colSpan: (cell) => cell.colSpan,
    columnSpan: (column) => column.span,
    fontsReady: () => document.fonts.ready,
    // The realm's own iterator, which page script can make endless, read under the bound.
    loadingFontFaces: () => {
      const faces = document.fonts.values();
      let loading = 0;
      for (let step = 0; step < COLLECTION_ITEM_LIMIT; step++) {
        const next = faces.next();
        if (!next || next.done) break;
        if (next.value && next.value.status === 'loading') loading += 1;
      }
      return loading;
    },
    addFontFace: (family, bytes) => {
      const face = new FontFace(family, new Uint8Array(bytes));
      if (face.status !== 'loaded') return null;
      document.fonts.add(face);
      return face;
    },
    deleteFontFace: (face) => {
      document.fonts.delete(face);
    },
  };

  // One capture per pass, made on first use, so no pass re-enters the iframe per call.
  let domAccessCache = null;
  function domAccess() {
    if (!domAccessCache) {
      domAccessCache = capturePristineDomAccess() || OWN_DOM_ACCESS;
    }
    return domAccessCache;
  }

  // A bound that is reached is a bug, so it is announced, once per pass, never
  // per item: what the collection lost (a part, diagnosticTokens), then where
  // (a part's key).
  let collectionLossReported = false;
  function reportCollectionLoss(what, where) {
    if (collectionLossReported) return;
    collectionLossReported = true;
    diagnose('collection', what, where);
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
    if (child) reportCollectionLoss(diagnosticTokens('truncatedItems', COLLECTION_ITEM_LIMIT), 'childNodesOf');
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
    if (child) reportCollectionLoss(diagnosticTokens('truncatedItems', COLLECTION_ITEM_LIMIT), 'elementChildrenOf');
    return elements;
  }

  // A static NodeList has no sibling chain, so it is an index loop over the pristine length.
  function nodeListToArray(list) {
    const reported = domAccess().nodeListLength(list);
    const length = Math.min(reported, COLLECTION_ITEM_LIMIT);
    const nodes = [];
    for (let index = 0; index < length; index++) nodes.push(list[index]);
    if (reported > COLLECTION_ITEM_LIMIT) {
      reportCollectionLoss(
        diagnosticTokens('truncatedOfItems', COLLECTION_ITEM_LIMIT, pageNumber(reported)), 'nodeListToArray');
    } else if (!(reported >= 0)) {
      // A length that is not a number empties the loop: terminating, but content loss all the same.
      reportCollectionLoss(diagnosticTokens('droppedLength', diagnosticPageText(reported)), 'nodeListToArray');
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
