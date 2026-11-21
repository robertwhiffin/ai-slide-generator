// Text metrics: what the text layout (snapshot_text.mjs) measures with
// offscreen probes in the page's own fonts. snapshot_text.mjs composes
// TEXT_METRICS_SOURCE into TEXT_SOURCE, and createTextLayout makes it once
// (createTextMetrics). Its header's "Metrics" says what is read and why;
// here are the probes themselves (measureProbes) and what is made of them:
// * after the walk, the characters each queued run's webfont lacks, each made
//   a run of its own in a face every app has (splitFallbackRuns), then every
//   queued paragraph's line height and ascent and every queued run's
//   optical-size and unkerned tracking (applyMetrics);
// * before the walk, every list marker's advance (measureMarkers);
// * while the walk reads, a face's content area, once per face
//   (contentHeightOf, for turned text), and the probe CSS of a face as the
//   browser sets it (browserCutCss, for the ellipsis advance).
//
// Runs in the page, inside the snapshot IIFE, after DOM_ACCESS_SOURCE:
// domAccess, queryOne and COLLECTION_ITEM_LIMIT are its free names. It is
// stringified, so it closes over nothing on the Node side; what it needs from
// the text layout arrives in `layout`, documented in snapshot_text.mjs:
//   codePointLength   (text, index) -> the length of the code point there;
//   familyOf          a font-family stack -> the face a run names;
//   probeFaceOf       (style, family, scale) -> the face a probe is set in;
//   pendingParagraphs, pendingRuns   what the walk queued for applyMetrics;
//   coverageFont      {family, advanceEm, bytes}, the coverage probe font
//                     (coverage_font.mjs).
// It gives back applyMetrics, browserCutCss, contentHeightOf, measureMarkers
// and measureProbes.

function createTextMetrics(layout) {
  const {
    codePointLength,
    familyOf,
    probeFaceOf,
    pendingParagraphs,
    pendingRuns,
    coverageFont,
  } = layout;

  // Metric probes: a <div> on documentElement, offscreen and hidden, so it
  // moves nothing in body's layout; white-space: pre so it never wraps, and no
  // box edges, so its border box is its text.
  const PROBE_STYLE = 'position:absolute;left:-10000px;top:0;visibility:hidden;white-space:pre;' +
    'margin:0;padding:0;border:0;text-indent:0;text-transform:none;';
  // Under line-height: normal the probe's height is the face's natural line height.
  const LINE_PROBE_TEXT = 'Hg';
  // An empty inline-block sits with its bottom on the baseline; at zero height
  // its top is the baseline too.
  const BASELINE_MARKER_STYLE = 'display:inline-block;width:0;height:0;vertical-align:baseline;' +
    'margin:0;padding:0;border:0;';
  // The optical size of the static cut PowerPoint and Google Slides draw (DM Sans
  // ships it as its text cut), and how far a run's width there may differ from
  // the browser's before the deck for Google Slides compensates it
  // (CALIBRATION.md A1; the deck for PowerPoint has no band, X1).
  const EXPORT_CUT_OPTICAL_SIZE = 14;
  const OPTICAL_SIZE_THRESHOLD = 0.005;
  // Characters a renderer spaces as one with the character before them: combining
  // marks, the zero-width joiners and the variation selectors.
  const JOINS_PREVIOUS = /^[\p{M}‌‍︀-️\u{E0100}-\u{E01EF}]$/u;
  // A line the browser set at least this much further down than its spacing
  // grew (markLineGrowth); less is layout rounding.
  const LINE_GROWTH_MIN_PX = 0.5;
  // Keeps a whole number of px that float division lands a hair under from
  // being rounded down a px (aboveLeadingPx).
  const ROUNDING_EPSILON = 1e-6;
  // A face's content area (ascent plus descent) as a multiple of its size,
  // taken where its probe could not be read: the faces decks use run 1.1 to 1.3.
  const FALLBACK_CONTENT_EM = 1.2;
  // Fallback faces (scripts/export_fidelity/CALIBRATION.md D8). A character a
  // run's webfont lacks the browser draws from another face: one after it in
  // the run's stack, or one the machine picks (Hiragino Sans for ▲ on a Mac,
  // whatever Linux has), and PowerPoint and Google Slides each pick their own
  // (Times New Roman and Arial for ▲ in DM Sans). So each such character is a
  // run of its own, in the face of the run's generic family all three apps
  // have (snapshot_text.mjs fallbackFaceOf). Only WGL4's characters are taken
  // out, the set Arial, Times New Roman and Courier New all cover in
  // PowerPoint for Windows and Mac and in Google Slides, less ASCII, which
  // every text face holds; a character outside it no fallback face covers
  // everywhere, so it stays in its run. Inclusive ranges, in order.
  const FALLBACK_COVERAGE = [
    [0x00a0, 0x017f], [0x0192, 0x0192], [0x01fa, 0x01ff], [0x02c6, 0x02c7], [0x02c9, 0x02c9],
    [0x02d8, 0x02dd], [0x0384, 0x038a], [0x038c, 0x038c], [0x038e, 0x03a1], [0x03a3, 0x03ce],
    [0x0401, 0x040c], [0x040e, 0x044f], [0x0451, 0x045c], [0x045e, 0x045f], [0x0490, 0x0491],
    [0x1e80, 0x1e85], [0x1ef2, 0x1ef3], [0x2013, 0x2015], [0x2017, 0x201e], [0x2020, 0x2022],
    [0x2026, 0x2026], [0x2030, 0x2030], [0x2032, 0x2033], [0x2039, 0x203a], [0x203c, 0x203c],
    [0x203e, 0x203e], [0x2044, 0x2044], [0x207f, 0x207f], [0x20a3, 0x20a4], [0x20a7, 0x20a7],
    [0x20ac, 0x20ac], [0x2105, 0x2105], [0x2113, 0x2113], [0x2116, 0x2116], [0x2122, 0x2122],
    [0x2126, 0x2126], [0x212e, 0x212e], [0x215b, 0x215e], [0x2190, 0x2195], [0x21a8, 0x21a8],
    [0x2202, 0x2202], [0x2206, 0x2206], [0x220f, 0x220f], [0x2211, 0x2212], [0x2215, 0x2215],
    [0x2219, 0x221a], [0x221e, 0x221f], [0x2229, 0x2229], [0x222b, 0x222b], [0x2248, 0x2248],
    [0x2260, 0x2261], [0x2264, 0x2265], [0x2302, 0x2302], [0x2310, 0x2310], [0x2320, 0x2321],
    [0x2500, 0x2500], [0x2502, 0x2502], [0x250c, 0x250c], [0x2510, 0x2510], [0x2514, 0x2514],
    [0x2518, 0x2518], [0x251c, 0x251c], [0x2524, 0x2524], [0x252c, 0x252c], [0x2534, 0x2534],
    [0x253c, 0x253c], [0x2550, 0x256c], [0x2580, 0x2580], [0x2584, 0x2584], [0x2588, 0x2588],
    [0x258c, 0x258c], [0x2590, 0x2593], [0x25a0, 0x25a1], [0x25aa, 0x25ac], [0x25b2, 0x25b2],
    [0x25ba, 0x25ba], [0x25bc, 0x25bc], [0x25c4, 0x25c4], [0x25ca, 0x25cb], [0x25cf, 0x25cf],
    [0x25d8, 0x25d9], [0x25e6, 0x25e6], [0x263a, 0x263c], [0x2640, 0x2640], [0x2642, 0x2642],
    [0x2660, 0x2660], [0x2663, 0x2663], [0x2665, 0x2666], [0x266a, 0x266b], [0xfb01, 0xfb02],
  ];
  // What a coverage probe never asks about: white space, and the marks and
  // format characters that join or space the text around them.
  const COVERAGE_SKIP = /[\s\p{M}\p{Cf}]/u;
  // A coverage probe's size, and the share of the coverage glyph's advance a
  // probe reaching it must have: no text face's glyph is near 4 em wide.
  const COVERAGE_PROBE_PX = 100;
  const COVERAGE_SHARE = 0.75;

  const dom = domAccess();
  // The content area per probe face, how tall its Range rect is, in unscaled
  // px (null when it could not be measured), measured once each
  // (contentHeightOf).
  const contentHeights = Object.create(null);

  // The characters a renderer spaces after: code points, less the ones that
  // join the character before them.
  function characterCount(text) {
    let count = 0;
    let index = 0;
    while (index < text.length) {
      const length = codePointLength(text, index);
      if (!JOINS_PREVIOUS.test(text.slice(index, index + length))) count++;
      index += length;
    }
    return count;
  }

  // The size of each {css, text, baseline} probe, in order: one <div> per probe
  // on documentElement (PROBE_STYLE plus its css), all appended first so one
  // layout serves every read, then each read and removed. A baseline probe
  // also holds, before its text, a zero-size inline-block on the baseline, and
  // reports `ascent`: from its text's top (the glyph top the walk reads with a
  // Range) down to that baseline; and `content`, how tall its text's Range
  // rect is, the face's content area. Null when the page would not take them,
  // which is announced with `loss`, what the slide then exports without. The
  // text goes in as a text node: page script can take away the textContent
  // setter (hostile_text_nodes). Every probe is made, put in and taken off
  // through the pristine realm (dom_access.mjs): page script can make the
  // page's own remove do nothing, and a probe left after body would restyle
  // what the walk reads (html > body:not(:last-child)).
  function measureProbes(probes, loss) {
    const elements = [];
    const parts = [];
    let sizes = [];
    try {
      const root = queryOne('html');
      for (let index = 0; index < probes.length; index++) {
        const element = dom.createElement('div');
        dom.setAttribute(element, 'style', PROBE_STYLE + probes[index].css);
        let marker = null;
        if (probes[index].baseline) {
          marker = dom.createElement('span');
          dom.setAttribute(marker, 'style', BASELINE_MARKER_STYLE);
          dom.appendChild(element, marker);
        }
        const text = dom.createTextNode(probes[index].text);
        dom.appendChild(element, text);
        dom.appendChild(root, element);
        elements.push(element);
        parts.push({ marker, text });
      }
      const range = document.createRange();
      for (let index = 0; index < elements.length; index++) {
        const rect = elements[index].getBoundingClientRect();
        const size = { w: Number(rect.width), h: Number(rect.height) };
        if (parts[index].marker) {
          range.setStart(parts[index].text, 0);
          range.setEnd(parts[index].text, probes[index].text.length);
          const textRect = range.getBoundingClientRect();
          size.ascent = Number(parts[index].marker.getBoundingClientRect().top) - Number(textRect.top);
          size.content = Number(textRect.height);
        }
        sizes.push(size);
      }
    } catch (e) {
      console.warn('[html2pptx] the text metric probes could not be read (' + (e && e.message) + '); ' + loss);
      sizes = null;
    } finally {
      for (let index = 0; index < elements.length; index++) {
        try { dom.remove(elements[index]); } catch (e) { /* already detached: nothing to undo */ }
      }
    }
    return sizes;
  }

  // A face's line, as line-height: normal sets it: its height is the natural
  // line height, its baseline probe the ascent.
  function lineProbeCss(face) {
    return face.font + 'font-optical-sizing:' + face.optical + ';font-variation-settings:' + face.variation +
      ';line-height:normal;letter-spacing:0;';
  }

  // The width the browser draws a run at: its face as the element sets it.
  function browserCutCss(face) {
    return face.font + face.typesetting + 'font-optical-sizing:' + face.optical +
      ';font-variation-settings:' + face.variation + ';';
  }

  // The width PowerPoint and Google Slides draw it at: the same face at the
  // export cut's optical size. A repeated axis takes its last value, so the
  // element's own settings keep every other axis.
  function exportCutCss(face) {
    const own = face.variation === 'normal' ? '' : face.variation + ',';
    return face.font + face.typesetting + 'font-optical-sizing:auto;font-variation-settings:' + own +
      '"opsz" ' + EXPORT_CUT_OPTICAL_SIZE + ';';
  }

  // The width PowerPoint for Mac draws it at: the export cut with no pair
  // kerning. It kerns no DM Sans (its kerning is GPOS alone), and the deck
  // for it turns PowerPoint's kerning off with every spc it writes (pptxgenjs
  // kern="0"), Arial's too (scripts/export_fidelity/CALIBRATION.md X1). The
  // later font-kerning wins over the element's; a "kern" feature the element
  // sets would turn kerning back on, so one turning it off follows its own (a
  // repeated feature takes its last value).
  function unkernedCutCss(face) {
    const own = face.features === 'normal' ? '' : face.features + ',';
    return exportCutCss(face) + 'font-kerning:none;font-feature-settings:' + own + '"kern" 0;';
  }

  // Whether the code point is one FALLBACK_COVERAGE holds.
  function inFallbackCoverage(codePoint) {
    for (let index = 0; index < FALLBACK_COVERAGE.length; index++) {
      if (codePoint < FALLBACK_COVERAGE[index][0]) return false;
      if (codePoint <= FALLBACK_COVERAGE[index][1]) return true;
    }
    return false;
  }

  // One character set in `face` alone, the coverage probe font after it: its
  // face's own advance where the face draws it, COVERAGE_ADVANCE_EM where not.
  // Nothing the page sets on the root may widen it.
  function coverageCss(face) {
    return face.coverage + '"' + coverageFont.family + '";font-size:' + COVERAGE_PROBE_PX + 'px;' +
      'font-size-adjust:none;letter-spacing:0;word-spacing:0;font-feature-settings:normal;font-variant:normal;';
  }

  // Whether `family` is a webfont the page loaded (`webfonts`, model.fonts);
  // CSS family names match case-insensitively.
  function isWebfont(webfonts, family) {
    const wanted = String(family || '').toLowerCase();
    const names = Object.keys(webfonts || {});
    for (let index = 0; index < names.length && index < COLLECTION_ITEM_LIMIT; index++) {
      if (names[index].toLowerCase() === wanted) return true;
    }
    return false;
  }

  // The pieces `text` is cut into, in order, {start, end, fallback}: a run of
  // characters its face lacks (`lacking`, their offsets in order), or of the
  // rest. A character that joins the one before it (a variation selector
  // after ▲) stays with it.
  function piecesOf(text, lacking) {
    const pieces = [];
    let at = 0;
    let next = 0;
    while (at < text.length) {
      const fallback = next < lacking.length && lacking[next] === at;
      if (fallback) next += 1;
      let end = at + codePointLength(text, at);
      while (end < text.length && JOINS_PREVIOUS.test(text.slice(end, end + codePointLength(text, end)))) {
        end += codePointLength(text, end);
      }
      const last = pieces.length ? pieces[pieces.length - 1] : null;
      if (last && last.fallback === fallback) last.end = end;
      else pieces.push({ start: at, end, fallback });
      at = end;
    }
    return pieces;
  }

  // The coverage probes of every queued run of a webfont, one per distinct face
  // and character it might lack; what each run asks, {pending, asked: [{at,
  // probe}]}, for the runs that ask anything.
  function coverageQuestions(webfonts, list) {
    const questions = [];
    for (let index = 0; index < pendingRuns.length; index++) {
      const pending = pendingRuns[index];
      if (!isWebfont(webfonts, pending.run.family)) continue;
      const text = pending.run.text;
      const css = coverageCss(pending.face);
      const asked = [];
      let at = 0;
      while (at < text.length) {
        const length = codePointLength(text, at);
        const character = text.slice(at, at + length);
        if (!COVERAGE_SKIP.test(character) && inFallbackCoverage(character.codePointAt(0))) {
          asked.push({ at, probe: list.probe(css, character, false) });
        }
        at += length;
      }
      if (asked.length) questions.push({ pending, asked });
    }
    return questions;
  }

  // Puts `pieces` (runs) where `run` is in `runs`, a line's runs.
  function replaceRun(runs, run, pieces) {
    for (let index = 0; index < runs.length; index++) {
      if (runs[index] !== run) continue;
      runs.splice(index, 1, ...pieces);
      return;
    }
  }

  // splitFallbackRuns(webfonts): every queued run of a webfont the page loaded
  // (`webfonts`, model.fonts) with characters its face lacks is cut into runs
  // (piecesOf), in place in its line. A piece of such characters is the run's
  // style in its fallback face (snapshot_text.mjs fallbackFaceOf), with no
  // measured tracking, and leaves the queue: its width in the export is its
  // fallback face's. Every other piece stays queued, its width now probed at
  // the browser's own cut. Which characters a face lacks is read from the face
  // itself, the same on every machine: one probe pass with the coverage probe
  // font added to the document's fonts (dom_access.mjs addFontFace) and
  // deleted again. A run of a family that is no webfont is a font on the
  // viewer's machine, whose coverage is that machine's own, so it is left.
  function splitFallbackRuns(webfonts) {
    const list = probeList();
    const questions = coverageQuestions(webfonts, list);
    if (!questions.length) return;
    const loss = 'this slide exports the characters its webfonts lack in its own fonts, as each app falls back';
    let face = null;
    let sizes = null;
    try {
      face = dom.addFontFace(coverageFont.family, coverageFont.bytes);
    } catch (e) {
      face = null;
    }
    if (!face) {
      console.warn('[html2pptx] the coverage probe font could not be added; ' + loss);
      return;
    }
    try {
      sizes = measureProbes(list.probes, loss);
    } finally {
      try {
        dom.deleteFontFace(face);
      } catch (e) {
        console.warn('[html2pptx] the coverage probe font could not be deleted (' + (e && e.message) + ')');
      }
    }
    if (!sizes) return;
    const lackingAt = COVERAGE_SHARE * coverageFont.advanceEm * COVERAGE_PROBE_PX;
    const split = [];
    for (let index = 0; index < questions.length; index++) {
      const lacking = [];
      for (let ask = 0; ask < questions[index].asked.length; ask++) {
        const size = sizes[questions[index].asked[ask].probe];
        if (size && size.w >= lackingAt) lacking.push(questions[index].asked[ask].at);
      }
      if (lacking.length) split.push({ pending: questions[index].pending, lacking });
    }
    if (!split.length) return;
    const queued = [];
    let next = 0;
    for (let index = 0; index < pendingRuns.length; index++) {
      const pending = pendingRuns[index];
      if (next >= split.length || split[next].pending !== pending) {
        queued.push(pending);
        continue;
      }
      const run = pending.run;
      const pieces = piecesOf(run.text, split[next].lacking);
      next += 1;
      const written = [];
      for (let piece = 0; piece < pieces.length; piece++) {
        const part = { ...run, text: run.text.slice(pieces[piece].start, pieces[piece].end) };
        if (pieces[piece].fallback) {
          part.family = pending.face.fallback;
          part.opticalTrackingPx = 0;
          part.unkernedTrackingPx = 0;
        } else {
          queued.push({
            run: part,
            runs: pending.runs,
            face: pending.face,
            width: null,
            endsLine: pending.endsLine && piece === pieces.length - 1,
          });
        }
        written.push(part);
      }
      replaceRun(pending.runs, run, written);
    }
    pendingRuns.length = 0;
    for (let index = 0; index < queued.length; index++) pendingRuns.push(queued[index]);
  }

  // The distinct probes of one measureProbes pass: probe(css, text, baseline)
  // adds one unless it is there already, and returns its index in `probes`.
  function probeList() {
    const probes = [];
    const probeIndex = Object.create(null);
    function probe(css, text, baseline) {
      const key = (baseline ? 'b' : 'w') + css + '\u0000' + text;
      if (probeIndex[key] === undefined) {
        probeIndex[key] = probes.length;
        probes.push({ css, text, baseline });
      }
      return probeIndex[key];
    }
    return { probes, probe };
  }

  // measureMarkers(markers): every marker's advance (snapshot.mjs ListMarker),
  // {full, glyphs}, the widths its whole text and its glyphs take in its own
  // face as the browser lays them out, its tabular-nums and every other
  // feature included, in unscaled CSS px. A probe of a text marker's whole
  // text is as wide as the box Chrome laid it out in, so the two widths give
  // the trailing white space that box holds. One probe pass, made before the
  // walk reads any rect: the probes are gone again by then. A marker whose
  // probes could not be read keeps a null advance.
  function measureMarkers(markers) {
    const list = probeList();
    const wanted = [];
    const length = Math.min(markers.length, COLLECTION_ITEM_LIMIT);
    for (let index = 0; index < length; index++) {
      const marker = markers[index];
      if (!marker.list.glyphs) continue;
      const css = browserCutCss(probeFaceOf(marker.style, familyOf(marker.style.fontFamily), 1));
      wanted.push({
        marker,
        full: list.probe(css, marker.text, false),
        glyphs: list.probe(css, marker.list.glyphs, false),
      });
    }
    if (!wanted.length) return;
    const sizes = measureProbes(list.probes, 'this slide exports its list markers at their boxes, ' +
      'trailing space included, and joins each inside one to its line as the browser laid it out');
    if (!sizes) return;
    let unmeasured = 0;
    for (let index = 0; index < wanted.length; index++) {
      const full = sizes[wanted[index].full].w;
      const glyphs = sizes[wanted[index].glyphs].w;
      if (Number.isFinite(full) && Number.isFinite(glyphs) && full >= 0 && glyphs >= 0) {
        wanted[index].marker.list.advance = { full, glyphs };
      } else {
        unmeasured += 1;
      }
    }
    if (unmeasured) {
      console.warn('[html2pptx] list markers: ' + unmeasured + ' of ' + wanted.length + ' marker width(s) ' +
        'measured no finite size; those markers are placed at their boxes, trailing space included, ' +
        'and an inside one joins its line as the browser laid it out');
    }
  }

  // applyMetrics() fills in what the walk queued, in place on the blocks it
  // returned (they are the slide model's items by then):
  // * every paragraph's lineHeightPx, its CSS line height (line-height: normal
  //   is the natural one, from the probe), and ascentPx, its largest run's
  //   distance from glyph top to baseline. The emitter turns them into the
  //   renderers' spacing and the first-line offset (emit_text.cjs);
  // * every run's opticalTrackingPx, where the export cut and the browser's
  //   width differ by more than OPTICAL_SIZE_THRESHOLD: the browser's width
  //   less the export cut's, per character. Both widths carry the run's CSS
  //   tracking, which the emitter writes on top, so it is not counted twice.
  //   The deck for Google Slides, which kerns, writes it;
  // * every run's unkernedTrackingPx, which the deck for PowerPoint writes:
  //   the same per-character delta with no band, plus the run's kerning (its
  //   export cut's width less the unkerned cut's) per gap its tracking can
  //   close. PowerPoint puts a run's tracking after each of its characters,
  //   the last included, so a run another follows on its line spreads its
  //   kerning over all of them, and the run after it starts where the
  //   browser's does; a run that ends its line over the gaps between them,
  //   so its last glyph ends where the browser's does (CALIBRATION.md X1).
  // Each distinct probe is measured once. First the characters each run's
  // webfont lacks are split off (splitFallbackRuns), so their runs are the ones
  // measured. `webfonts` is model.fonts.
  function applyMetrics(webfonts) {
    splitFallbackRuns(webfonts);
    const list = probeList();
    const probes = list.probes;
    const probe = list.probe;
    const paragraphProbes = [];
    for (let index = 0; index < pendingParagraphs.length; index++) {
      const face = pendingParagraphs[index].face;
      paragraphProbes.push(face ? probe(lineProbeCss(face), LINE_PROBE_TEXT, true) : -1);
    }
    const runProbes = [];
    for (let index = 0; index < pendingRuns.length; index++) {
      const pending = pendingRuns[index];
      runProbes.push({
        exportCut: probe(exportCutCss(pending.face), pending.run.text, false),
        unkernedCut: probe(unkernedCutCss(pending.face), pending.run.text, false),
        browserCut: pending.width === null ? probe(browserCutCss(pending.face), pending.run.text, false) : -1,
      });
    }
    const sizes = probes.length
      ? measureProbes(probes, 'this slide exports without line spacing, optical-size and kerning tracking')
      : [];
    if (!sizes) return;

    for (let index = 0; index < pendingParagraphs.length; index++) {
      const pending = pendingParagraphs[index];
      if (paragraphProbes[index] < 0) continue;
      const line = sizes[paragraphProbes[index]];
      if (!(line.h > 0)) continue;
      const lineHeight = /px$/.test(pending.lineHeight) ? parseFloat(pending.lineHeight) : line.h;
      if (lineHeight > 0) pending.paragraph.lineHeightPx = lineHeight * pending.face.scale;
      if (line.ascent > 0) pending.paragraph.ascentPx = line.ascent * pending.face.scale;
      markLineGrowth(pending);
    }

    for (let index = 0; index < pendingRuns.length; index++) {
      const pending = pendingRuns[index];
      const scale = pending.face.scale;
      const drawn = pending.width === null ? sizes[runProbes[index].browserCut].w * scale : pending.width;
      const exportCut = sizes[runProbes[index].exportCut].w * scale;
      const unkernedCut = sizes[runProbes[index].unkernedCut].w * scale;
      const characters = characterCount(pending.run.text);
      if (!(drawn > 0 && exportCut > 0 && characters > 0)) continue;
      const delta = (drawn - exportCut) / characters;
      if (Math.abs(exportCut - drawn) / drawn > OPTICAL_SIZE_THRESHOLD) pending.run.opticalTrackingPx = delta;
      const gaps = pending.endsLine ? characters - 1 : characters;
      const kerning = unkernedCut > 0 && gaps > 0 ? (exportCut - unkernedCut) / gaps : 0;
      pending.run.unkernedTrackingPx = delta + kerning;
    }
  }

  // Marks each line of a pending paragraph that the browser set further down
  // than its spacing puts it, with that much more, growthPx: a raised inline
  // (a vertical-align: super run with a line height of its own) grows its
  // line's box, so the line's own text starts lower than the paragraph's
  // spacing alone would put it. Read from where each line's body starts
  // (paragraphsOf), against the last line before it that holds text: in its
  // own paragraph, a line height per line between them; for the first line
  // of a later paragraph of the block, in the one before (laterParagraphGrowth).
  // The block's first line is placed by its block's own geometry. A growth
  // under LINE_GROWTH_MIN_PX is layout rounding. The emitter reads it where a
  // renderer grows a line by what the line holds (emit_text.cjs).
  function markLineGrowth(pending) {
    const pitch = pending.paragraph.lineHeightPx;
    if (!(pitch > 0)) return;
    let previous = -1;
    for (let index = 0; index < pending.bodies.length; index++) {
      const body = pending.bodies[index];
      if (body === null) continue;
      const growth = previous >= 0
        ? body.top - pending.bodies[previous].top - (index - previous) * pitch
        : index === 0 ? laterParagraphGrowth(pending, body) : NaN;
      if (growth >= LINE_GROWTH_MIN_PX) pending.paragraph.lines[index].growthPx = growth;
      previous = index;
    }
  }

  // How much further down than its spacing the browser set the first line of
  // a later paragraph of a block (`pending`, that line's body `body`), against
  // the last line of the paragraph before that holds text (`pending.previous`);
  // NaN for the block's first paragraph, or where that line was not read.
  // Between lines of different sizes, CSS sets each line's content inside its
  // own line height, the leading split above and below it, as the emitter
  // spaces them (emit_text.cjs: half each paragraph's leading before the line);
  // Chrome rounds the half above down to a whole px (aboveLeadingPx). So the
  // later line's body starts the earlier one's line height (and one more per
  // blank line between them) less the earlier one's leading above, plus its
  // own, below the earlier line's body.
  function laterParagraphGrowth(pending, body) {
    const before = pending.previous;
    if (!before || !(before.paragraph.lineHeightPx > 0)) return NaN;
    let last = before.bodies.length - 1;
    while (last >= 0 && before.bodies[last] === null) last--;
    if (last < 0) return NaN;
    const earlier = before.bodies[last];
    const pitch = before.paragraph.lineHeightPx;
    const blanks = before.bodies.length - 1 - last;
    const spacing = (1 + blanks) * pitch - aboveLeadingPx(pitch, earlier.height, before.face.scale) +
      aboveLeadingPx(pending.paragraph.lineHeightPx, body.height, pending.face.scale);
    return body.top - earlier.top - spacing;
  }

  // The leading Chrome sets above a line's content (`contentHeight`) in its
  // line height (`lineHeight`), both in slide px at `scale`: half their
  // difference, rounded down to a whole CSS px.
  function aboveLeadingPx(lineHeight, contentHeight, scale) {
    const unit = scale > 0 ? scale : 1;
    return Math.floor((lineHeight - contentHeight) / unit / 2 + ROUNDING_EPSILON) * unit;
  }

  // How tall the content area of a run set in probe face `face` is (its
  // Range rect), in slide px: by probe (measureProbes `content`), once per
  // face, made when a turned line first needs it and off the page again
  // before the layout reads another rect. A face whose probe could not be
  // read is taken as FALLBACK_CONTENT_EM of the run's `sizePx`.
  function contentHeightOf(face, sizePx) {
    const css = lineProbeCss(face);
    if (contentHeights[css] === undefined) {
      const sizes = measureProbes([{ css, text: LINE_PROBE_TEXT, baseline: true }],
        'turned text is placed across its lines by its font size, not by its face');
      const content = sizes ? Number(sizes[0].content) : NaN;
      contentHeights[css] = Number.isFinite(content) && content > 0 ? content : null;
    }
    const content = contentHeights[css];
    return content === null ? sizePx * FALLBACK_CONTENT_EM : content * face.scale;
  }

  return { applyMetrics, browserCutCss, contentHeightOf, measureMarkers, measureProbes };
}

export const TEXT_METRICS_SOURCE = createTextMetrics.toString();
