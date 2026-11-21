// Native tables: a <table> the browser laid out as a plain grid becomes one
// editable table on the slide (an a:tbl in a p:graphicFrame), with the
// browser's own grid, spans, fills, collapsed borders and cell margins.
// snapshot.mjs composes TABLE_SOURCE into its page IIFE and calls collectTable
// when its walk visits a <table>. For a table it returns, the walk draws the
// table's own background, radius and shadow as a shape under the table (its
// border too, in the separated model, where it frames the cells from outside),
// pushes the table item over it, draws no box of the table's rows, row groups,
// columns and cells (the item holds their fills and borders), gives each
// cell's text to collectCellText, which makes it that cell's paragraphs where
// an a:tc paragraph can hold it (snapshot_text.mjs layoutCell) and overlay
// text items where not, and still visits everything the cells hold, so a
// pill, a Harvey ball or a cell's ::before dot is an item of its own over the
// table. emit_table.cjs writes it.
//
// The grid (HTML §4.9.12, the table model). Each row's cells take, in order,
// the first grid columns no cell from a row above still covers; rowspan
// reaches at most the end of the cell's row group, rowspan="0" exactly that
// far. Rows are in the order the browser shows them: the first header group,
// then every other group and row in document order, then the first footer
// group. Columns run left to right on the slide, so a right-to-left table's
// first column is its rightmost. Each grid line is where the browser put the
// cell edges on it, on the whole px nearest it, as Chrome paints a box edge
// (snappedLines): under border-collapse: collapse adjacent cells' boxes share
// their edges (each the centre line of the collapsed border between them);
// under separate, the line is the middle of the gap between them.
//
// The fill of a cell is what its table's renderer paints in it: its column
// group's, its column's, its row group's, its row's and its own backgrounds,
// in that order, each over the ones before it (CSS 2.1 §17.5.1). The table's
// own background is no cell's: it is the shape under the table.
//
// Borders. Under border-collapse: collapse every shared edge has one line,
// which CSS 2.1 §17.6.2.1 picks from the borders of every element meeting
// there (borderWinner): `hidden` wins, then the wider border, then the style
// (double, solid, dashed, dotted, ridge, outset, groove, inset), then the
// origin (a cell, a row, a row group, a column, a column group, the table),
// then the element further up, and further left (right, in a right-to-left
// table). The winner is written on BOTH cells' sides, so neither PowerPoint
// nor Drive sees one cell's line contradicting its neighbour's. Under
// separate, each cell's border is its own; with no spacing between cells, two
// that meet put both their borders side by side, one line as wide as both when
// they are alike. A cell spanning several of the other side's cells
// has one side for all of them, so every edge that a span connects takes the
// strongest of its winners.
//
// Margins. A cell's content starts where the browser started it: its
// padding, plus half the collapsed border on that side (collapse) or its own
// whole border (separate), plus the distance from its grid line to its box
// (the half gap a separated table's spacing leaves, and the part of a px its
// line moved to a whole one), less the room its text needs to keep the
// browser's lines (fitCellText).
//
// A cell's content stays the cell's own wherever an a:tbl paragraph can hold
// it. A cell holding block layout (a <div>, a <p>, a float) keeps the
// table native, its fill and borders on its a:tc, and gives its whole content
// to the walk as overlay items at their measured places (paragraphs null): its
// lines are blocks of their own, which no a:tc paragraph is. So does a cell
// whose line holds an atomic inline, an edged inline or a painted inline box,
// and one whose own overflow clip cuts its text (layoutCell, fitCellText).
//
// What no a:tbl can draw is positioned items instead: cell boxes as shapes,
// cell text as text items, all editable, as every slide box is drawn. A table
// is native only when (collectTable returns null otherwise):
// * it is a <table> laid out as display: table holding no nested <table>,
//   whose children are captions, column groups, columns, row groups and rows,
//   each the table part its tag is, holding no text of their own, rows holding
//   cells, and no part but a cell generating a ::before or ::after (each would
//   be an anonymous table box);
// * every part paints as a cell of an a:tbl can: shown, in flow (static, or
//   relative where gridOf finds it on its grid), untransformed, without a
//   background image, a shadow or an effect;
// * its cells do not stand apart: a separated table whose spacing
//   exceeds SPACING_VISIBLE_PX on either axis has no cell that paints a fill
//   or a border, and no separated cell that paints rounds its corners;
// * any two separated borders side by side are the same colour and style;
// * its spans can be read and its grid holds at most COLLECTION_ITEM_LIMIT
//   slots (an [html2pptx] line says when not: slotsOf);
// * the browser's cell boxes are its grid (gridOf).
// snapshot.mjs checks the rest before it asks: the table is shown, untouched
// by any clip and unrotated.
//
// /**
//  * TableLayout = {collapse, item, parts, cells}   (page-side only)
//  *   collapse  border-collapse: collapse, whose table border is the grid's;
//  *   item      the TableItem, its cells' text still to come (snapshot.mjs);
//  *   parts     every element whose box the item draws: row groups, rows,
//  *             columns, column groups and cells;
//  *   cells     cell element -> {model: TableCell, grid: {left, top, right, bottom},
//  *             blocks}: blocks when it holds block layout (holdsInlineContent),
//  *             whose content is overlay items whatever it holds.
//  *
//  * TableItem = {kind:'table', x, y, colWidths:number[], rowHeights:number[], cells:TableCell[]}
//  *   x, y       the grid's top left: its first column and row lines, slide px;
//  *              every grid line is on a whole px, so are x, y and each size;
//  *   cells      one per cell, row by row, left to right, spans included, plus an
//  *              empty one for each grid slot no cell covers (a short row).
//  * TableCell = {row, col, rowspan, colspan, fill:{color,alpha}|null,
//  *              borders:{top,right,bottom,left: {color, alpha, widthPx, dash}|null},
//  *              margin:{top,right,bottom,left}, valign:'top'|'middle'|'bottom',
//  *              align:'left'|'center'|'right', rtl, font:{family, weight, italic, sizePx},
//  *              paragraphs: Paragraph[] | null}
//  *   row, col   its top left grid slot, columns left to right on the slide;
//  *   borders    each side's line, the same on the cell across it; a colour
//  *              written solid, composited over what it paints on, as text
//  *              colours are (Drive drops line alpha);
//  *   margin     where its content starts inside its grid cell, px;
//  *   font       its own face: what an empty line and a paragraph mark are set in;
//  *   paragraphs its text (snapshot_text.mjs Paragraph); null when its text is
//  *              overlay text items instead (layoutCell), and [] when it has none.
//  */

// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE:
// domAccess, elementChildrenOf, childNodesOf, queryAllWithin and the two limits
// are its free names. It is stringified, so it closes over nothing on the Node
// side; what it needs from the snapshot arrives in `env`:
//   parseColour      css colour -> {color, alpha, r, g, b} | null;
//   paintedColour    (css colour, opacity) -> {color, alpha} | null, as painted;
//   paintOver        (layer {color, alpha}, backdrop) -> the backdrop with the layer over it;
//   solidColour      (layer {color, alpha}, backdrop) -> 'RRGGBB', the layer painted
//                    over the backdrop and every opacity group it is in;
//   backdropInside   (backdrop, style) -> the backdrop of the content inside that element;
//   opacityOf        computed style -> its own opacity;
//   pseudoOf         element -> {before, after, marker} it generates, or null;
//   rectOf           element -> its border box bounds, {left, top, width, height};
//   fontOf           (style, scale) -> its own face (snapshot_text.mjs fontOf);
//   layoutCell       (element, style, walk) -> a cell's CellText (snapshot_text.mjs layoutCell);
//   collectText      (element, style, paint, seq, walk) -> lays out an element's text as
//                    overlay text items, as anywhere on the slide (snapshot.mjs);
//   placeGroups      (groups, paint, seq) -> places inline groups as overlay items (snapshot.mjs).
function createTableLayout(env) {
  const TEXT_NODE = 3;
  const dom = domAccess();
  // The display each table part's tag lays out as. A part another display
  // makes into something else (td { display: block }) is no grid part.
  const PART_DISPLAY = {
    caption: 'table-caption',
    colgroup: 'table-column-group',
    col: 'table-column',
    thead: 'table-header-group',
    tbody: 'table-row-group',
    tfoot: 'table-footer-group',
    tr: 'table-row',
    td: 'table-cell',
    th: 'table-cell',
  };
  // A border-spacing above this on either axis is a gap the eye sees.
  const SPACING_VISIBLE_PX = 0.5;
  // Grid lines that run backwards by under this are in order, and a cell box
  // within this of its grid cell (plus the spacing around it) lies on it:
  // layout rounding.
  const LINE_EPSILON_PX = 0.5;
  const CELL_EPSILON_PX = 1;
  // Border widths this close are equal, and so are two colours' alphas.
  const WIDTH_EPSILON_PX = 0.01;
  const ALPHA_EPSILON = 0.001;
  // CSS 2.1 §17.6.2.1: the styles, then the origins, from strongest to weakest.
  // Read with hasOwnProperty, plain tables: page script can replace Map and Set.
  const STYLE_RANK = { double: 8, solid: 7, dashed: 6, dotted: 5, ridge: 4, outset: 3, groove: 2, inset: 1 };
  const ORIGIN_RANK = { cell: 6, row: 5, rowGroup: 4, column: 3, columnGroup: 2, table: 1 };
  const SIDES = ['top', 'right', 'bottom', 'left'];

  function tagOf(element) {
    return String(dom.tagName(element) || '').toLowerCase();
  }

  function rank(table, key) {
    return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : 0;
  }

  // Whether every text node among an element's children is CSS white space: a
  // table, row group or row whose own text is anything else holds an
  // anonymous cell for it.
  function holdsOnlyWhiteSpace(element) {
    const nodes = childNodesOf(element);
    for (let index = 0; index < nodes.length; index++) {
      if (dom.nodeType(nodes[index]) !== TEXT_NODE) continue;
      if (/[^ \t\n\r\f]/.test(String(dom.textData(nodes[index]) || ''))) return false;
    }
    return true;
  }

  // Whether an element generates a ::before or ::after, which inside a table
  // structure is an anonymous cell or row of its own.
  function generatesContent(element) {
    const pseudo = env.pseudoOf(element);
    return Boolean(pseudo && (pseudo.before || pseudo.after));
  }

  function isSet(value, none) {
    return Boolean(value) && value !== none;
  }

  // Whether a table part paints and lays out as the part of an a:tbl it
  // becomes: shown, in flow, untransformed, its background a colour at most,
  // with no shadow and no effect. Opacity it may have: its fill keeps it as
  // alpha and its text and lines are composited through it. Relative
  // positioning keeps it in flow; an offset that moves it off its grid cell
  // is caught by gridOf.
  function plainPart(s) {
    return s.visibility === 'visible' && (s.position === 'static' || s.position === 'relative') &&
      s.transform === 'none' && !isSet(s.rotate, 'none') && !isSet(s.scale, 'none') && !isSet(s.translate, 'none') &&
      s.filter === 'none' && !isSet(s.backdropFilter, 'none') && s.mixBlendMode === 'normal' &&
      !isSet(s.clipPath, 'none') && !isSet(s.maskImage, 'none') && !isSet(s.webkitMaskImage, 'none') &&
      !isSet(s.boxShadow, 'none') && !isSet(s.backgroundImage, 'none');
  }

  // The part an element is, by its tag, when it lays out as that part. A
  // cell's own ::before and ::after are its content (holdsInlineContent reads
  // how they lay out); any other part's would be an anonymous table box.
  function partOf(element, s) {
    const name = tagOf(element);
    if (!Object.prototype.hasOwnProperty.call(PART_DISPLAY, name) || s.display !== PART_DISPLAY[name]) return null;
    if (name === 'caption') return name;
    const cell = name === 'td' || name === 'th';
    if (!plainPart(s) || (!cell && generatesContent(element))) return null;
    return name;
  }

  // ─── structure ───────────────────────────────────────────────────────
  // readStructure(table) -> Structure | null, null for anything but the plain
  // structure the grid can be read from:
  //   Structure = {groups, columns, parts}
  //   groups   [{style, rows: [{element, style, cells: [{element, style}]}]}]
  //            in the order the browser shows them; a run of <tr> children of
  //            the table is one anonymous group (style null);
  //   columns  [{style, groupStyle}] per grid column, from the column groups
  //            and columns (style or groupStyle null where none is set);
  //   parts    every element whose box the table draws.
  // Every list is bounded: elementChildrenOf by COLLECTION_ITEM_LIMIT, and the
  // parts read in all by the same limit.
  function readStructure(table) {
    const parts = [];
    const columns = [];
    const bodies = [];
    let header = null;
    let footer = null;
    let anonymous = null;
    if (!holdsOnlyWhiteSpace(table)) return null;
    const children = elementChildrenOf(table);
    for (let index = 0; index < children.length; index++) {
      const child = children[index];
      const s = window.getComputedStyle(child);
      if (s.display === 'none') continue;
      const part = partOf(child, s);
      if (!part) return null;
      if (part === 'tr') {
        if (!anonymous) {
          anonymous = { style: null, rows: [] };
          bodies.push(anonymous);
        }
        if (!readRow(child, s, anonymous, parts)) return null;
        continue;
      }
      anonymous = null;
      if (part === 'caption') continue;
      if (part === 'colgroup' || part === 'col') {
        if (!readColumns(child, part, s, columns, parts)) return null;
        continue;
      }
      if (part !== 'thead' && part !== 'tbody' && part !== 'tfoot') return null;
      const group = { style: s, rows: [] };
      if (!readGroup(child, group, parts)) return null;
      parts.push(child);
      // The first header group shows above every other row, the first footer group below.
      if (part === 'thead' && !header) header = group;
      else if (part === 'tfoot' && !footer) footer = group;
      else bodies.push(group);
      if (parts.length > COLLECTION_ITEM_LIMIT) return null;
    }
    const groups = (header ? [header] : []).concat(bodies, footer ? [footer] : []);
    return { groups, columns, parts };
  }

  function readGroup(element, group, parts) {
    if (!holdsOnlyWhiteSpace(element)) return false;
    const rows = elementChildrenOf(element);
    for (let index = 0; index < rows.length; index++) {
      const s = window.getComputedStyle(rows[index]);
      if (s.display === 'none') continue;
      if (partOf(rows[index], s) !== 'tr' || !readRow(rows[index], s, group, parts)) return false;
      if (parts.length > COLLECTION_ITEM_LIMIT) return false;
    }
    return true;
  }

  function readRow(element, s, group, parts) {
    if (!holdsOnlyWhiteSpace(element)) return false;
    const row = { element, style: s, cells: [] };
    const cells = elementChildrenOf(element);
    for (let index = 0; index < cells.length; index++) {
      const cs = window.getComputedStyle(cells[index]);
      if (cs.display === 'none') continue;
      const part = partOf(cells[index], cs);
      if (part !== 'td' && part !== 'th') return false;
      row.cells.push({ element: cells[index], style: cs, blocks: !holdsInlineContent(cells[index]) });
      parts.push(cells[index]);
      if (parts.length > COLLECTION_ITEM_LIMIT) return false;
    }
    group.rows.push(row);
    parts.push(element);
    return true;
  }

  // Whether a box is out of the flow its parent lays out, as an absolutely
  // positioned one is: the walk draws it as items of its own over the table.
  function outOfFlow(s) {
    return s.position === 'absolute' || s.position === 'fixed';
  }

  // Whether a display is inline-level: an inline box, or an atomic inline
  // (inline-block, inline-flex, an inline replaced element) whose content
  // paints as an item of its own over the table.
  function inlineLevel(display) {
    return display === 'inline' || /^inline[- ]/.test(display) || /^ruby/.test(display);
  }

  // Whether a cell holds inline-level content only, which its paragraphs and
  // the items over it can draw. A cell that does not holds block layout:
  // a block-level child (a <div>, a <p>, a ::before laid out as a
  // block) is a block of its own in the cell, and a float moves the lines
  // beside it, which no a:tc paragraph does, so the walk overlays its whole
  // content. The children of an inline box and of a display: contents one are
  // its own; an atomic inline and an out-of-flow box are items of their own,
  // whatever they hold. Bounded by WALK_STEP_LIMIT in depth and
  // COLLECTION_ITEM_LIMIT in all; past either it holds block layout.
  function holdsInlineContent(cell) {
    const generated = env.pseudoOf(cell);
    const pseudos = generated ? [generated.before, generated.after] : [];
    for (let index = 0; index < pseudos.length; index++) {
      const pseudo = pseudos[index];
      if (pseudo && pseudo.style.display !== 'none' && !outOfFlow(pseudo.style) && !inlineLevel(String(pseudo.style.display))) return false;
    }
    const pending = [{ element: cell, depth: 0 }];
    let read = 0;
    while (pending.length) {
      const next = pending.pop();
      if (next.depth >= WALK_STEP_LIMIT) return false;
      const children = elementChildrenOf(next.element);
      read += children.length;
      if (read > COLLECTION_ITEM_LIMIT) return false;
      for (let index = 0; index < children.length; index++) {
        const s = window.getComputedStyle(children[index]);
        const display = String(s.display);
        if (display === 'none' || outOfFlow(s)) continue;
        if (s.float && s.float !== 'none') return false;
        if (display === 'contents' || display === 'inline') {
          pending.push({ element: children[index], depth: next.depth + 1 });
        } else if (!inlineLevel(display)) {
          return false;
        }
      }
    }
    return true;
  }

  // A <col> covers `span` grid columns; a <colgroup> covers its <col>s' or,
  // holding none, its own span.
  function readColumns(element, part, s, columns, parts) {
    parts.push(element);
    if (part === 'col') {
      return addColumns(columns, spanOf(dom.columnSpan, element), s, null);
    }
    const held = elementChildrenOf(element);
    let shown = 0;
    for (let index = 0; index < held.length; index++) {
      const cs = window.getComputedStyle(held[index]);
      if (cs.display === 'none') continue;
      if (partOf(held[index], cs) !== 'col') return false;
      parts.push(held[index]);
      if (!addColumns(columns, spanOf(dom.columnSpan, held[index]), cs, s)) return false;
      shown++;
    }
    return shown > 0 || addColumns(columns, spanOf(dom.columnSpan, element), null, s);
  }

  function addColumns(columns, span, style, groupStyle) {
    if (span === null) return positioned('a column\'s span could not be read');
    const count = Number.isInteger(span) && span > 0 ? span : 1;
    if (columns.length + count > WALK_STEP_LIMIT) return positioned('its columns pass ' + WALK_STEP_LIMIT);
    for (let index = 0; index < count; index++) columns.push({ style, groupStyle });
    return true;
  }

  // A span the browser lays a cell or column out with (dom_access.mjs rowSpan,
  // colSpan, columnSpan), or null when it cannot be read: an element tagged
  // td, th, col or colgroup that slide script made in another namespace is no
  // table element, and its pristine getter throws.
  function spanOf(read, element) {
    try {
      return Number(read(element));
    } catch (e) {
      return null;
    }
  }

  // Announces why a table whose structure is plain still cannot be an a:tbl,
  // and gives the positioned-items answer, null (falsy for addColumns' callers).
  function positioned(reason) {
    console.warn('[html2pptx] native table: ' + reason + '; it exports as positioned items');
    return null;
  }

  // ─── the grid ────────────────────────────────────────────────────────
  // slotsOf(groups) -> {rows, cells, slots, columns} | null: the rows in order,
  // each cell with its grid slot and spans in HTML column order, slots[r][c]
  // the index in `cells` of the cell covering slot (r, c), and the column
  // count. Null, announced (positioned), when a span cannot be read, past
  // WALK_STEP_LIMIT rows or columns, or past COLLECTION_ITEM_LIMIT slots in
  // the grid's area or under its cells: no slide holds such a table, and its
  // grid would be that many cells. Null too when two cells' spans overlap,
  // which no a:tbl can hold (model_check.cjs drops such a grid).
  function slotsOf(groups) {
    const rows = [];
    const groupEnd = [];
    for (let group = 0; group < groups.length; group++) {
      const end = rows.length + groups[group].rows.length;
      for (let row = 0; row < groups[group].rows.length; row++) {
        rows.push({ element: groups[group].rows[row].element, style: groups[group].rows[row].style, group, cells: groups[group].rows[row].cells });
        groupEnd.push(end);
      }
    }
    if (!rows.length) return null;
    if (rows.length > WALK_STEP_LIMIT) return positioned('its ' + rows.length + ' rows pass ' + WALK_STEP_LIMIT);
    const slots = [];
    for (let row = 0; row < rows.length; row++) slots.push([]);
    const cells = [];
    let columns = 0;
    let covered = 0;
    for (let row = 0; row < rows.length; row++) {
      let column = 0;
      for (let index = 0; index < rows[row].cells.length; index++) {
        const read = rows[row].cells[index];
        while (slots[row][column] !== undefined) column++;
        const reach = groupEnd[row] - row;
        const rowSpanRead = spanOf(dom.rowSpan, read.element);
        const colSpanRead = spanOf(dom.colSpan, read.element);
        if (rowSpanRead === null || colSpanRead === null) return positioned('a cell\'s spans could not be read');
        const rowspan = rowSpanRead === 0 ? reach : Math.min(Math.max(1, rowSpanRead || 1), reach);
        const colspan = Math.max(1, colSpanRead || 1);
        if (column + colspan > WALK_STEP_LIMIT) return positioned('its columns pass ' + WALK_STEP_LIMIT);
        covered += rowspan * colspan;
        if (covered > COLLECTION_ITEM_LIMIT) return positioned('its cells cover more than ' + COLLECTION_ITEM_LIMIT + ' grid slots');
        for (let down = 0; down < rowspan; down++) {
          for (let across = 0; across < colspan; across++) {
            // Spans the HTML table model lets overlap (a row span reaching a
            // later row's column span): the browser draws both, an a:tbl
            // holds one cell per slot.
            if (slots[row + down][column + across] !== undefined) {
              return positioned('two of its cells cover one grid slot');
            }
            slots[row + down][column + across] = cells.length;
          }
        }
        cells.push({ element: read.element, style: read.style, blocks: read.blocks, row, col: column, rowspan, colspan });
        column += colspan;
        columns = Math.max(columns, column);
      }
    }
    // Every slot of the grid is a cell of the a:tbl, those no cell covers included.
    if (rows.length * columns > COLLECTION_ITEM_LIMIT) {
      return positioned('its grid of ' + rows.length + ' rows by ' + columns + ' columns passes ' +
        COLLECTION_ITEM_LIMIT + ' slots');
    }
    return columns > 0 ? { rows, cells, slots, columns } : null;
  }

  // The position of each of `count + 1` grid lines from the cell edges on it:
  // `starts[k]` the edges of the cells that start at line k, `ends[k]` of those
  // that end there. A line with both lies half way between the last end and
  // the first start (the middle of a separated table's gap; one edge under
  // collapse). A line with neither (every cell spans it) is interpolated
  // between its neighbours; `fallback(k)` places one no cell bounds at all.
  function linesOf(count, starts, ends, fallback) {
    const lines = [];
    for (let line = 0; line <= count; line++) {
      let first = Infinity;
      let last = -Infinity;
      for (let index = 0; index < starts[line].length; index++) first = Math.min(first, starts[line][index]);
      for (let index = 0; index < ends[line].length; index++) last = Math.max(last, ends[line][index]);
      if (Number.isFinite(first) && Number.isFinite(last)) lines.push((first + last) / 2);
      else if (Number.isFinite(first)) lines.push(first);
      else if (Number.isFinite(last)) lines.push(last);
      else lines.push(fallback(line));
    }
    for (let line = 1; line < count; line++) {
      if (Number.isFinite(lines[line])) continue;
      let next = line + 1;
      while (next < count && !Number.isFinite(lines[next])) next++;
      lines[line] = lines[line - 1] + (lines[next] - lines[line - 1]) / (next - line + 1);
    }
    return lines;
  }

  function emptyLists(count) {
    const lists = [];
    for (let index = 0; index <= count; index++) lists.push([]);
    return lists;
  }

  // gridOf(model, spacing) -> {columnLines, rowLines} | null: the grid lines
  // the browser's cell boxes lie on (the empty cells of short rows have no
  // box, and bound no line). Null unless they run in order and each cell box
  // lies on its grid cell, give or take the spacing around it: a layout whose
  // cells do not tile the HTML grid is no a:tbl.
  function gridOf(model, spacing) {
    const columnStarts = emptyLists(model.columns);
    const columnEnds = emptyLists(model.columns);
    const rowStarts = emptyLists(model.rows.length);
    const rowEnds = emptyLists(model.rows.length);
    for (let index = 0; index < model.cells.length; index++) {
      const cell = model.cells[index];
      const rect = cell.rect;
      if (!rect) continue;
      columnStarts[cell.visualCol].push(rect.left);
      columnEnds[cell.visualCol + cell.colspan].push(rect.right);
      rowStarts[cell.row].push(rect.top);
      rowEnds[cell.row + cell.rowspan].push(rect.bottom);
    }
    const rowRects = [];
    for (let row = 0; row < model.rows.length; row++) rowRects.push(env.rectOf(model.rows[row].element));
    const rowLines = linesOf(model.rows.length, rowStarts, rowEnds, (line) => (line < model.rows.length
      ? Number(rowRects[line].top)
      : Number(rowRects[line - 1].top) + Number(rowRects[line - 1].height)));
    const columnLines = linesOf(model.columns, columnStarts, columnEnds, () => NaN);
    if (!inOrder(rowLines) || !inOrder(columnLines)) return null;
    const reachX = spacing.x + CELL_EPSILON_PX;
    const reachY = spacing.y + CELL_EPSILON_PX;
    for (let index = 0; index < model.cells.length; index++) {
      const cell = model.cells[index];
      if (!cell.rect) continue;
      if (Math.abs(cell.rect.left - columnLines[cell.visualCol]) > reachX ||
          Math.abs(cell.rect.right - columnLines[cell.visualCol + cell.colspan]) > reachX ||
          Math.abs(cell.rect.top - rowLines[cell.row]) > reachY ||
          Math.abs(cell.rect.bottom - rowLines[cell.row + cell.rowspan]) > reachY) return null;
    }
    return { columnLines, rowLines };
  }

  function inOrder(lines) {
    for (let index = 0; index < lines.length; index++) {
      if (!Number.isFinite(lines[index])) return false;
      if (index > 0 && lines[index] < lines[index - 1] - LINE_EPSILON_PX) return false;
    }
    return true;
  }

  // ─── borders ─────────────────────────────────────────────────────────
  // One element's border on one side, as a candidate for the edge it lies on:
  // {style, widthPx, colour, origin, backdrop}. widthPx is 0 for a style that
  // paints nothing; colour is its own (parseColour), backdrop what it paints
  // over, through which it is written solid.
  function sideOf(s, side, origin, scale, backdrop) {
    const name = side.charAt(0).toUpperCase() + side.slice(1);
    const style = String(s['border' + name + 'Style'] || 'none');
    const width = style === 'none' || style === 'hidden' ? 0 : (parseFloat(s['border' + name + 'Width']) || 0) * scale;
    return { style, widthPx: width, colour: env.parseColour(s['border' + name + 'Color']), origin, backdrop };
  }

  function paints(candidate) {
    return candidate.widthPx > 0 && candidate.style !== 'none' && candidate.style !== 'hidden';
  }

  // The border CSS 2.1 §17.6.2.1 keeps of two meeting at one edge, `first`
  // being the one further up, or further to the table's start: hidden, then
  // width, then style, then origin, then position.
  function borderWinner(first, second) {
    if (first.style === 'hidden') return first;
    if (second.style === 'hidden') return second;
    if (!paints(second)) return first;
    if (!paints(first)) return second;
    if (Math.abs(first.widthPx - second.widthPx) > WIDTH_EPSILON_PX) return first.widthPx > second.widthPx ? first : second;
    const styles = rank(STYLE_RANK, first.style) - rank(STYLE_RANK, second.style);
    if (styles) return styles > 0 ? first : second;
    const origins = rank(ORIGIN_RANK, first.origin) - rank(ORIGIN_RANK, second.origin);
    if (origins) return origins > 0 ? first : second;
    return first;
  }

  function strongest(candidates) {
    let winner = null;
    for (let index = 0; index < candidates.length; index++) {
      winner = winner ? borderWinner(winner, candidates[index]) : candidates[index];
    }
    return winner;
  }

  // The line a winning border draws, or null: hidden, painting nothing, or
  // transparent. Its colour is written solid, over what it paints on.
  function lineOf(winner) {
    if (!shows(winner)) return null;
    return {
      color: env.solidColour(winner.colour, winner.backdrop),
      alpha: 1,
      widthPx: winner.widthPx,
      dash: winner.style === 'dashed' || winner.style === 'dotted' ? (winner.style === 'dashed' ? 'dash' : 'dot') : 'solid',
    };
  }

  // Every edge of the grid, as runs of the slot boundaries one decision
  // covers: [{horizontal, segments: [{first, second, line, slot}]}] where
  // `first` is the index of the cell above (or to the left), `second` of the
  // cell below (or to the right), either null on the table's outside, `line`
  // the grid line and `slot` the row or column the boundary lies along. Two
  // neighbouring boundaries are one run while one cell lies along both: a cell
  // has one side, so every boundary its side touches gets one line. A
  // boundary inside a spanning cell is no edge and ends a run.
  function edgeRuns(model) {
    const runs = [];
    const rows = model.rows.length;
    const columns = model.columns;
    const slots = model.visualSlots;
    for (let line = 0; line <= rows; line++) {
      runsAlong(runs, true, line, columns, (slot) => [line > 0 ? slots[line - 1][slot] : null, line < rows ? slots[line][slot] : null]);
    }
    for (let line = 0; line <= columns; line++) {
      runsAlong(runs, false, line, rows, (slot) => [line > 0 ? slots[slot][line - 1] : null, line < columns ? slots[slot][line] : null]);
    }
    return runs;
  }

  // The runs along one grid line of `count` boundaries; `cellsAt(slot)` is
  // [first, second] at one of them.
  function runsAlong(runs, horizontal, line, count, cellsAt) {
    let run = null;
    for (let slot = 0; slot < count; slot++) {
      const cells = cellsAt(slot);
      const first = cells[0];
      const second = cells[1];
      if (first !== null && first === second) {
        run = null;
        continue;
      }
      const previous = run ? run.segments[run.segments.length - 1] : null;
      const sharesACell = Boolean(previous) &&
        ((first !== null && previous.first === first) || (second !== null && previous.second === second));
      if (!sharesACell) {
        run = { horizontal, segments: [] };
        runs.push(run);
      }
      run.segments.push({ first, second, line, slot });
    }
  }

  // The candidates meeting on one collapsed boundary, the ones further up
  // (or to the start) of each origin first. Rows and row groups border
  // horizontal lines across the table and its left and right edges;
  // columns and column groups vertical lines down it and its top and bottom.
  function collapsedCandidates(model, run, segment) {
    const candidates = [];
    const cellSide = (index, side) => model.cells[index].sides[side];
    if (run.horizontal) {
      const line = segment.line;
      if (segment.first !== null) candidates.push(cellSide(segment.first, 'bottom'));
      if (segment.second !== null) candidates.push(cellSide(segment.second, 'top'));
      if (line > 0) candidates.push(model.rows[line - 1].sides.bottom);
      if (line < model.rows.length) candidates.push(model.rows[line].sides.top);
      const groupAbove = line > 0 ? model.rows[line - 1].group : -1;
      const groupBelow = line < model.rows.length ? model.rows[line].group : -1;
      if (groupAbove !== groupBelow) {
        if (groupAbove >= 0 && model.groups[groupAbove].sides) candidates.push(model.groups[groupAbove].sides.bottom);
        if (groupBelow >= 0 && model.groups[groupBelow].sides) candidates.push(model.groups[groupBelow].sides.top);
      }
      if (line === 0 || line === model.rows.length) {
        const side = line === 0 ? 'top' : 'bottom';
        const column = model.visualColumns[segment.slot];
        if (column && column.sides) candidates.push(column.sides[side]);
        if (column && column.groupSides) candidates.push(column.groupSides[side]);
        candidates.push(model.tableSides[side]);
      }
      return candidates;
    }
    const line = segment.line;
    // Further to the start is further left, or right in a right-to-left table.
    const startward = model.rtl ? [segment.second, 'left', segment.first, 'right'] : [segment.first, 'right', segment.second, 'left'];
    if (startward[0] !== null) candidates.push(cellSide(startward[0], startward[1]));
    if (startward[2] !== null) candidates.push(cellSide(startward[2], startward[3]));
    const before = line > 0 ? model.visualColumns[line - 1] : null;
    const after = line < model.columns ? model.visualColumns[line] : null;
    const columnPair = model.rtl ? [after, 'left', before, 'right'] : [before, 'right', after, 'left'];
    for (let index = 0; index < 4; index += 2) {
      if (columnPair[index] && columnPair[index].sides) candidates.push(columnPair[index].sides[columnPair[index + 1]]);
    }
    if (!before || !after || before.groupStyle !== after.groupStyle) {
      for (let index = 0; index < 4; index += 2) {
        if (columnPair[index] && columnPair[index].groupSides) candidates.push(columnPair[index].groupSides[columnPair[index + 1]]);
      }
    }
    if (line === 0 || line === model.columns) {
      const side = line === 0 ? 'left' : 'right';
      const row = model.rows[segment.slot];
      candidates.push(row.sides[side]);
      if (model.groups[row.group].sides) candidates.push(model.groups[row.group].sides[side]);
      candidates.push(model.tableSides[side]);
    }
    return candidates;
  }

  // The separated borders meeting on one boundary: each cell's own,
  // and with no spacing two that meet are drawn side by side, as one line as
  // wide as both when they are alike. Undefined when they differ: no one
  // line draws them.
  function separatedWinner(model, run, segment) {
    const near = segment.first !== null ? model.cells[segment.first].sides[run.horizontal ? 'bottom' : 'right'] : null;
    const far = segment.second !== null ? model.cells[segment.second].sides[run.horizontal ? 'top' : 'left'] : null;
    const nearShows = shows(near);
    const farShows = shows(far);
    if (!nearShows || !farShows) return nearShows ? near : farShows ? far : null;
    if (near.style !== far.style || near.colour.color !== far.colour.color ||
        Math.abs(near.colour.alpha - far.colour.alpha) > ALPHA_EPSILON) return undefined;
    return { style: near.style, widthPx: near.widthPx + far.widthPx, colour: near.colour, origin: 'cell', backdrop: near.backdrop };
  }

  // Whether a candidate border (or null) paints a colour the eye sees.
  function shows(side) {
    return Boolean(side && paints(side) && side.colour && side.colour.alpha > 0);
  }

  // Writes each edge's line on both its cells, and the width the collapsed
  // edge takes into each cell (`share`, for the margins). False when a
  // separated edge cannot be one line.
  function resolveBorders(model) {
    const runs = edgeRuns(model);
    for (let index = 0; index < runs.length; index++) {
      const run = runs[index];
      const winners = [];
      for (let segment = 0; segment < run.segments.length; segment++) {
        const winner = model.collapse
          ? strongest(collapsedCandidates(model, run, run.segments[segment]))
          : model.adjacent ? separatedWinner(model, run, run.segments[segment]) : null;
        if (winner === undefined) return false;
        if (winner) winners.push(winner);
      }
      const winner = strongest(winners);
      const line = lineOf(winner);
      const width = winner && winner.style !== 'hidden' && paints(winner) ? winner.widthPx : 0;
      for (let segment = 0; segment < run.segments.length; segment++) {
        const ends = [[run.segments[segment].first, run.horizontal ? 'bottom' : 'right'], [run.segments[segment].second, run.horizontal ? 'top' : 'left']];
        for (let end = 0; end < 2; end++) {
          if (ends[end][0] === null) continue;
          const cell = model.cells[ends[end][0]];
          cell.lines[ends[end][1]] = line;
          cell.share[ends[end][1]] = width / 2;
        }
      }
    }
    return true;
  }

  // ─── fills ───────────────────────────────────────────────────────────
  // What a cell's renderer fills it with: its backgrounds, bottom first, each
  // painted over the ones before it, at the cumulative opacity of the element
  // it is on. Null when none shows.
  function fillOf(layers) {
    let fill = { color: '000000', alpha: 0, group: null };
    for (let index = 0; index < layers.length; index++) {
      const layer = layers[index] ? env.paintedColour(layers[index].value, layers[index].opacity) : null;
      if (layer) fill = env.paintOver(layer, fill);
    }
    return fill.alpha > 0 ? { color: fill.color, alpha: fill.alpha } : null;
  }

  // Whether a separated cell shows anything a gap would reveal: a fill
  // or a border.
  function cellShows(cell) {
    if (cell.fill) return true;
    for (let index = 0; index < SIDES.length; index++) {
      if (shows(cell.sides[SIDES[index]])) return true;
    }
    return false;
  }

  // The vertical-align of a cell as the anchor of its text: anything but
  // middle and bottom (baseline, a length) sets its first line at the top.
  function anchorOf(s) {
    const value = String(s.verticalAlign);
    return value === 'middle' || value === 'bottom' ? value : 'top';
  }

  // border-spacing as {x, y} in slide px: one length for both axes, or two.
  function spacingOf(s, frame) {
    const lengths = String(s.borderSpacing || '0px').trim().split(/\s+/);
    const x = parseFloat(lengths[0]) || 0;
    const y = lengths.length > 1 ? parseFloat(lengths[1]) || 0 : x;
    return { x: x * frame.scaleX, y: y * frame.scaleY };
  }

  // collectTable(table, s, context) -> TableLayout | null (null: positioned items)
  //   table, s  the <table> the snapshot walk is visiting and its computed style;
  //   context   {opacity, frame, backdrop}: its cumulative opacity, its
  //             transform frame (unrotated) and the backdrop it sits on.
  function collectTable(table, s, context) {
    if (tagOf(table) !== 'table' || s.display !== 'table' || generatesContent(table)) return null;
    if (queryAllWithin(table, 'table').length) return null;
    const structure = readStructure(table);
    const slotted = structure ? slotsOf(structure.groups) : null;
    if (!slotted) return null;
    const frame = context.frame;
    const rtl = s.direction === 'rtl';
    const collapse = s.borderCollapse === 'collapse';
    const spacing = collapse ? { x: 0, y: 0 } : spacingOf(s, frame);
    const tableBackdrop = env.backdropInside(context.backdrop, s);
    const scaleOf = (side) => (side === 'left' || side === 'right' ? frame.scaleX : frame.scaleY);
    const sidesOf = (style, origin, backdrop) => {
      const sides = {};
      for (let index = 0; index < SIDES.length; index++) sides[SIDES[index]] = sideOf(style, SIDES[index], origin, scaleOf(SIDES[index]), backdrop);
      return sides;
    };
    const groups = [];
    for (let index = 0; index < structure.groups.length; index++) {
      const style = structure.groups[index].style;
      const opacity = context.opacity * (style ? env.opacityOf(style) : 1);
      const backdrop = style ? env.backdropInside(tableBackdrop, style) : tableBackdrop;
      groups.push({ style, opacity, backdrop, sides: style ? sidesOf(style, 'rowGroup', backdrop) : null });
    }
    const rows = [];
    for (let index = 0; index < slotted.rows.length; index++) {
      const read = slotted.rows[index];
      const group = groups[read.group];
      const backdrop = env.backdropInside(group.backdrop, read.style);
      rows.push({
        element: read.element,
        style: read.style,
        group: read.group,
        opacity: group.opacity * env.opacityOf(read.style),
        backdrop,
        sides: sidesOf(read.style, 'row', backdrop),
      });
    }
    // Columns in slide order; past the columns the table sets, a column has no style.
    const visualColumns = [];
    for (let visual = 0; visual < slotted.columns; visual++) {
      const column = structure.columns[rtl ? slotted.columns - 1 - visual : visual] || null;
      // groupStyle is its column group's computed style: the same object for
      // every column of one group, so it also tells the groups apart.
      visualColumns.push(column ? {
        style: column.style,
        groupStyle: column.groupStyle,
        sides: column.style ? sidesOf(column.style, 'column', tableBackdrop) : null,
        groupSides: column.groupStyle ? sidesOf(column.groupStyle, 'columnGroup', tableBackdrop) : null,
      } : null);
    }
    const model = {
      rows,
      groups,
      columns: slotted.columns,
      visualColumns,
      cells: [],
      visualSlots: [],
      collapse,
      rtl,
      adjacent: !collapse && spacing.x <= SPACING_VISIBLE_PX && spacing.y <= SPACING_VISIBLE_PX,
      tableSides: sidesOf(s, 'table', tableBackdrop),
    };
    for (let row = 0; row < rows.length; row++) model.visualSlots.push([]);
    for (let index = 0; index < slotted.cells.length; index++) {
      const read = slotted.cells[index];
      const row = rows[read.row];
      const visualCol = rtl ? slotted.columns - read.col - read.colspan : read.col;
      const backdrop = env.backdropInside(row.backdrop, read.style);
      const opacity = row.opacity * env.opacityOf(read.style);
      // A cell spanning columns shows each one's background in its part, which
      // one a:tc fill cannot: the column it starts in, in the table's own
      // direction, stands for them all.
      const column = visualColumns[rtl ? visualCol + read.colspan - 1 : visualCol];
      const group = groups[row.group];
      const layers = [
        column && column.groupStyle ? { value: column.groupStyle.backgroundColor, opacity: context.opacity } : null,
        column && column.style ? { value: column.style.backgroundColor, opacity: context.opacity } : null,
        group.style ? { value: group.style.backgroundColor, opacity: group.opacity } : null,
        { value: row.style.backgroundColor, opacity: row.opacity },
        { value: read.style.backgroundColor, opacity },
      ];
      model.cells.push({
        element: read.element,
        style: read.style,
        blocks: read.blocks,
        row: read.row,
        visualCol,
        rowspan: read.rowspan,
        colspan: read.colspan,
        rect: boundsOf(env.rectOf(read.element)),
        fill: fillOf(layers),
        sides: sidesOf(read.style, 'cell', backdrop),
        lines: { top: null, right: null, bottom: null, left: null },
        share: { top: 0, right: 0, bottom: 0, left: 0 },
      });
      for (let down = 0; down < read.rowspan; down++) {
        for (let across = 0; across < read.colspan; across++) model.visualSlots[read.row + down][visualCol + across] = index;
      }
    }
    // A slot no cell covers (a short row) is an empty cell of the grid: no
    // fill of a row or column paints there, nor any border of its own.
    const empty = { borderTopStyle: 'none', borderRightStyle: 'none', borderBottomStyle: 'none', borderLeftStyle: 'none' };
    for (let row = 0; row < rows.length; row++) {
      for (let col = 0; col < slotted.columns; col++) {
        if (model.visualSlots[row][col] !== undefined) continue;
        model.visualSlots[row][col] = model.cells.length;
        model.cells.push({
          element: null,
          style: null,
          row,
          visualCol: col,
          rowspan: 1,
          colspan: 1,
          rect: null,
          fill: null,
          sides: sidesOf(empty, 'cell', tableBackdrop),
          lines: { top: null, right: null, bottom: null, left: null },
          share: { top: 0, right: 0, bottom: 0, left: 0 },
        });
      }
    }
    // Cells that stand apart show their gaps when any of them paints.
    if (!collapse && !model.adjacent) {
      for (let index = 0; index < model.cells.length; index++) {
        if (model.cells[index].element && cellShows(model.cells[index])) return null;
      }
    }
    // A separated cell that paints may round its corners, which no a:tc does;
    // under collapse border-radius does not apply to a cell (CSS Backgrounds 3).
    if (!collapse) {
      for (let index = 0; index < model.cells.length; index++) {
        const cell = model.cells[index];
        if (cell.element && cellShows(cell) && roundsCorners(cell.style)) return null;
      }
    }
    const grid = gridOf(model, spacing);
    if (!grid || !resolveBorders(model)) return null;
    return layoutOf(model, grid, structure.parts, s, frame);
  }

  function roundsCorners(s) {
    const corners = [s.borderTopLeftRadius, s.borderTopRightRadius, s.borderBottomRightRadius, s.borderBottomLeftRadius];
    for (let index = 0; index < corners.length; index++) {
      if (parseFloat(corners[index]) > 0) return true;
    }
    return false;
  }

  function boundsOf(rect) {
    const left = Number(rect.left);
    const top = Number(rect.top);
    return { left, top, right: left + Number(rect.width), bottom: top + Number(rect.height) };
  }

  // Grid lines where Chrome paints them: each on the whole px nearest the
  // browser's line, a half rounding up. Chrome snaps every box edge to a whole
  // pixel, so two cell fills meet on a pixel boundary; meeting between two
  // pixels, they anti-alias into a light seam in PowerPoint's PDF, under Quartz
  // and MuPDF alike. Each line is snapped where it lies rather than each width
  // rounded, so the widths add up to the snapped outer lines' distance however
  // many there are, and a cell's margins, measured from its snapped lines,
  // keep its text where the browser set it (layoutOf).
  function snappedLines(lines) {
    const snapped = [];
    for (let index = 0; index < lines.length; index++) snapped.push(Math.round(lines[index]));
    return snapped;
  }

  // The TableLayout of a table whose grid and borders are read: each cell's
  // margins and the item it is drawn as. `parts` are the elements whose
  // boxes it draws, `s` the table's computed style. The grid is the browser's,
  // on whole px (snappedLines).
  function layoutOf(model, grid, parts, s, frame) {
    const collapse = model.collapse;
    const columnLines = snappedLines(grid.columnLines);
    const rowLines = snappedLines(grid.rowLines);
    const colWidths = [];
    const rowHeights = [];
    for (let index = 0; index < model.columns; index++) colWidths.push(Math.max(0, columnLines[index + 1] - columnLines[index]));
    for (let index = 0; index < model.rows.length; index++) rowHeights.push(Math.max(0, rowLines[index + 1] - rowLines[index]));
    const tableFont = env.fontOf(s, frame.scale);
    const cells = new Map();
    const modelCells = [];
    for (let index = 0; index < model.cells.length; index++) {
      const cell = model.cells[index];
      const gridRect = {
        left: columnLines[cell.visualCol],
        right: columnLines[cell.visualCol + cell.colspan],
        top: rowLines[cell.row],
        bottom: rowLines[cell.row + cell.rowspan],
      };
      const margin = { top: 0, right: 0, bottom: 0, left: 0 };
      if (cell.element) {
        // From the grid line to the cell's box, then its border's share, then its padding.
        const offsets = {
          top: cell.rect.top - gridRect.top,
          right: gridRect.right - cell.rect.right,
          bottom: gridRect.bottom - cell.rect.bottom,
          left: cell.rect.left - gridRect.left,
        };
        for (let side = 0; side < SIDES.length; side++) {
          const name = SIDES[side];
          const scale = name === 'left' || name === 'right' ? frame.scaleX : frame.scaleY;
          const padding = (parseFloat(cell.style['padding' + name.charAt(0).toUpperCase() + name.slice(1)]) || 0) * scale;
          const border = collapse ? cell.share[name] : cell.sides[name].widthPx;
          margin[name] = Math.max(0, offsets[name] + border + padding);
        }
      }
      const modelCell = {
        row: cell.row,
        col: cell.visualCol,
        rowspan: cell.rowspan,
        colspan: cell.colspan,
        fill: cell.fill,
        borders: { top: cell.lines.top, right: cell.lines.right, bottom: cell.lines.bottom, left: cell.lines.left },
        margin,
        valign: cell.element ? anchorOf(cell.style) : 'top',
        align: 'left',
        rtl: model.rtl,
        font: cell.element ? env.fontOf(cell.style, frame.scale) : tableFont,
        paragraphs: cell.element ? null : [],
      };
      modelCells.push(modelCell);
      if (cell.element) cells.set(cell.element, { model: modelCell, grid: gridRect, blocks: cell.blocks });
    }
    modelCells.sort((a, b) => a.row - b.row || a.col - b.col);
    return {
      collapse,
      parts,
      cells,
      item: {
        kind: 'table',
        x: columnLines[0],
        y: rowLines[0],
        colWidths,
        rowHeights,
        cells: modelCells,
      },
    };
  }

  // A line of text within this of its grid cell's edge still lies in it (layout rounding).
  const CELL_TEXT_EPSILON_PX = 0.5;

  // A native table cell's text: the cell's own paragraphs when its renderer
  // can set its lines as the browser did (snapshot_text.mjs layoutCell) and
  // fitCellText finds them room in the cell; else overlay text items, as any
  // other block's. A cell holding block layout is overlaid whole,
  // whatever its first run holds: its own text is an anonymous block beside
  // its block children, and the walk places each where the browser did. So is
  // a cell whose text is turned (a vertical header): a turned item over it.
  // `cell` is its {model, grid, blocks}.
  function collectCellText(element, s, paint, seq, walk, cell) {
    if (cell.blocks || walk.turned) {
      env.collectText(element, s, paint, seq, walk);
      return;
    }
    const text = env.layoutCell(element, s, walk);
    if (text.native && fitCellText(cell, text)) {
      cell.model.paragraphs = text.paragraphs();
      cell.model.align = text.align;
      cell.model.rtl = text.rtl;
      return;
    }
    env.placeGroups(text.groups(), paint, seq);
  }

  // Whether a cell's lines lie in its grid cell; if so, makes them the room
  // past the widest that a renderer needs so as not to wrap one (text.slack),
  // as far as the margin on the side the alignment grows holds it (both sides
  // of centred text), down to none. The other side keeps its margin, so the
  // lines start where the browser started them; a cell its text overflows
  // gives its text to overlay items instead.
  function fitCellText(cell, text) {
    if (!text.extent) return true;
    const grid = cell.grid;
    const margin = cell.model.margin;
    if (text.extent.left < grid.left - CELL_TEXT_EPSILON_PX || text.extent.right > grid.right + CELL_TEXT_EPSILON_PX) return false;
    const room = grid.right - grid.left - margin.left - margin.right - (text.extent.right - text.extent.left);
    const deficit = text.slack - room;
    if (!(deficit > 0)) return true;
    if (text.align === 'center') {
      margin.left = Math.max(0, margin.left - deficit / 2);
      margin.right = Math.max(0, margin.right - deficit / 2);
    } else if (text.align === 'right') {
      margin.left = Math.max(0, margin.left - deficit);
    } else {
      margin.right = Math.max(0, margin.right - deficit);
    }
    return true;
  }

  return { collectTable, collectCellText };
}

export const TABLE_SOURCE = createTableLayout.toString();
