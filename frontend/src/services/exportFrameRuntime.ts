/**
 * Trusted bootstrap inserted into every browser-side export document.
 * Runs inside `sandbox="allow-scripts"` and performs all DOM access.
 *
 * html2canvas is not imported here: Node-side Playwright tests import the
 * document builders, and `?raw` is a Vite loader. The parent controller
 * injects the pinned npm dist into HTML2CANVAS_SOURCE_PLACEHOLDER.
 */
import { FONT_REWRITE_SRC, WALKER_SOURCE } from './exportWalkerSource';

export const TELLR_EXPORT_FRAME_TYPE = 'tellr-export-frame';
export const EXPORT_FRAME_CHANNEL_PLACEHOLDER = '__TELLR_EXPORT_CHANNEL_ID__';
export const HTML2CANVAS_SOURCE_PLACEHOLDER = '__TELLR_HTML2CANVAS_SOURCE__';

function escapeEmbeddedScript(source: string): string {
  return source.replace(/<\/script/gi, '<\\/script');
}

const BOOTSTRAP_SOURCE = `
(function () {
  var TYPE = ${JSON.stringify(TELLR_EXPORT_FRAME_TYPE)};
  var CHANNEL_ID = ${JSON.stringify(EXPORT_FRAME_CHANNEL_PLACEHOLDER)};
  var FONT_REWRITE_SRC = ${JSON.stringify(FONT_REWRITE_SRC)};
  var SLIDE_WIDTH = 1280;
  var SLIDE_HEIGHT = 720;
  var SLIDE_SETTLE_MS = 400;

  var parentWin = window.parent;
  var postToParent = parentWin.postMessage.bind(parentWin);
  var addWinListener = window.addEventListener.bind(window);
  var setTimeoutFn = window.setTimeout.bind(window);
  var createEl = document.createElement.bind(document);
  var html2canvasFn = window.html2canvas;
  var extractSlide = window.__extractSlide;
  var prepareSlide = window.__prepareSlideForExtract;
  var handled = false;

  function post(payload) {
    payload.type = TYPE;
    payload.channelId = CHANNEL_ID;
    postToParent(payload, '*');
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeoutFn(resolve, ms); });
  }

  function safeMessage(err) {
    if (err && typeof err.message === 'string' && err.message) {
      return String(err.message).slice(0, 500);
    }
    return 'Export capture failed';
  }

  function fail(requestId, code, err) {
    post({
      requestId: requestId || '',
      kind: 'error',
      code: code,
      message: safeMessage(err)
    });
  }

  function findSlideRoot(doc) {
    var slide = doc.querySelector('.slide');
    if (!slide) return doc.body;
    var el = slide;
    while (el.parentElement && el.parentElement !== doc.body) {
      el = el.parentElement;
    }
    return el.parentElement === doc.body ? el : doc.body;
  }

  function forceRootSize(slideEl, doc) {
    if (slideEl && slideEl !== doc.body) {
      slideEl.style.width = SLIDE_WIDTH + 'px';
      slideEl.style.height = SLIDE_HEIGHT + 'px';
      slideEl.style.margin = '0';
      slideEl.style.boxSizing = 'border-box';
    }
  }

  async function waitForPdfCharts(maxWait) {
    var start = Date.now();
    while (typeof window.Chart === 'undefined' && Date.now() - start < maxWait) {
      await sleep(100);
    }
    if (typeof window.Chart === 'undefined') return;
    var canvases = document.querySelectorAll('canvas');
    if (canvases.length === 0) return;
    var allReady = false;
    var attempts = 0;
    while (!allReady && attempts < 50 && Date.now() - start < maxWait) {
      allReady = Array.prototype.every.call(canvases, function (canvas) {
        return canvas.width > 0 && canvas.height > 0;
      });
      if (!allReady) {
        await sleep(100);
        attempts++;
      }
    }
    if (allReady) await sleep(500);
  }

  async function waitForScreenshotCharts(maxMs) {
    var start = Date.now();
    while (typeof window.Chart === 'undefined' && Date.now() - start < 1500) {
      await sleep(80);
    }
    var canvases = document.querySelectorAll('canvas');
    if (!canvases.length) return;
    var deadline = start + maxMs;
    while (Date.now() < deadline) {
      var ready = Array.prototype.every.call(canvases, function (c) {
        return c.width > 0 && c.height > 0;
      });
      if (ready) break;
      await sleep(80);
    }
  }

  async function waitForPptxCharts(maxWait) {
    var start = Date.now();
    while (typeof window.Chart === 'undefined' && Date.now() - start < maxWait) {
      await sleep(100);
    }
    if (typeof window.Chart === 'undefined') return;
    var canvases = document.querySelectorAll('canvas');
    if (canvases.length === 0) {
      await sleep(500);
      return;
    }
    var allHaveDimensions = false;
    var attempts = 0;
    while (!allHaveDimensions && attempts < 50 && Date.now() - start < maxWait) {
      allHaveDimensions = Array.prototype.every.call(canvases, function (canvas) {
        return canvas.width > 0 && canvas.height > 0;
      });
      if (!allHaveDimensions) {
        await sleep(100);
        attempts++;
      }
    }
    var allReady = false;
    attempts = 0;
    while (!allReady && attempts < 50 && Date.now() - start < maxWait) {
      allReady = true;
      for (var i = 0; i < canvases.length; i++) {
        var canvas = canvases[i];
        var ctx = canvas.getContext('2d');
        if (ctx && canvas.width > 0 && canvas.height > 0) {
          try {
            var sampleWidth = Math.min(canvas.width, 400);
            var sampleHeight = Math.min(canvas.height, 400);
            var imageData = ctx.getImageData(0, 0, sampleWidth, sampleHeight);
            var data = imageData.data;
            var hasContent = false;
            var pixelCount = 0;
            for (var j = 3; j < data.length; j += 4) {
              if (data[j] > 0) {
                hasContent = true;
                pixelCount++;
              }
            }
            if (!hasContent || pixelCount < 100) {
              allReady = false;
              break;
            }
          } catch (e) {
            allReady = false;
            break;
          }
        } else {
          allReady = false;
          break;
        }
      }
      if (!allReady) {
        await sleep(100);
        attempts++;
      }
    }
    if (allReady) await sleep(1000);
  }

  function applyPdfSubtitleFixes(slideEl, iframeWindow) {
    var subtitleMargins = [];
    var subtitles = slideEl.querySelectorAll('.subtitle, p.subtitle, h2.subtitle, div.subtitle, [class*="subtitle"]');
    subtitles.forEach(function (subtitle) {
      subtitle.offsetHeight;
    });
    subtitles.forEach(function (subtitle) {
      var computedStyle = iframeWindow.getComputedStyle(subtitle);
      if (computedStyle) {
        var marginBottom = computedStyle.marginBottom;
        var margin = marginBottom && marginBottom !== '0px' ? marginBottom : '40px';
        subtitleMargins.push(margin);
        subtitle.style.setProperty('margin-bottom', margin, 'important');
        subtitle.style.marginBottom = margin;
        subtitle.style.setProperty('margin-top', '0', 'important');
        subtitle.style.marginTop = '0';
      } else {
        subtitleMargins.push('40px');
        subtitle.style.setProperty('margin-bottom', '40px', 'important');
        subtitle.style.marginBottom = '40px';
        subtitle.style.setProperty('margin-top', '0', 'important');
        subtitle.style.marginTop = '0';
      }
    });
    return subtitleMargins;
  }

  function pdfOnClone(clonedDoc, subtitleMargins) {
    var clonedHtml = clonedDoc.documentElement;
    var clonedBody = clonedDoc.body;
    clonedHtml.style.width = SLIDE_WIDTH + 'px';
    clonedHtml.style.height = SLIDE_HEIGHT + 'px';
    clonedHtml.style.overflow = 'hidden';
    clonedHtml.style.margin = '0';
    clonedHtml.style.padding = '0';
    clonedBody.style.width = SLIDE_WIDTH + 'px';
    clonedBody.style.height = SLIDE_HEIGHT + 'px';
    clonedBody.style.overflow = 'hidden';
    clonedBody.style.margin = '0';
    clonedBody.style.padding = '0';
    clonedBody.style.position = 'relative';
    clonedBody.style.boxSizing = 'border-box';
    var clonedSlide = clonedDoc.querySelector('.slide');
    if (clonedSlide) {
      clonedSlide.style.width = SLIDE_WIDTH + 'px';
      clonedSlide.style.height = SLIDE_HEIGHT + 'px';
      clonedSlide.style.margin = '0';
      clonedSlide.style.boxSizing = 'border-box';
    }
    var clonedSubtitles = clonedDoc.querySelectorAll('.subtitle, p.subtitle, h2.subtitle, div.subtitle, [class*="subtitle"]');
    clonedSubtitles.forEach(function (clonedSubtitle, index) {
      clonedSubtitle.style.boxSizing = 'border-box';
      var marginValue = '40px';
      if (index < subtitleMargins.length) {
        marginValue = subtitleMargins[index];
      } else {
        var computedStyle = clonedDoc.defaultView && clonedDoc.defaultView.getComputedStyle(clonedSubtitle);
        if (computedStyle) {
          var mb = computedStyle.marginBottom;
          marginValue = (mb && mb !== '0px') ? mb : '40px';
        }
      }
      clonedSubtitle.style.setProperty('margin-bottom', marginValue, 'important');
      clonedSubtitle.style.marginBottom = marginValue;
      clonedSubtitle.style.setProperty('margin-top', '0', 'important');
      clonedSubtitle.style.marginTop = '0';
      clonedSubtitle.offsetHeight;
      var cs = clonedDoc.defaultView && clonedDoc.defaultView.getComputedStyle(clonedSubtitle);
      if (cs) {
        var lineHeight = cs.lineHeight;
        if (lineHeight && lineHeight !== 'normal') {
          clonedSubtitle.style.lineHeight = lineHeight;
        }
      }
    });
    clonedDoc.querySelectorAll('h1, h2, h3').forEach(function (el) {
      el.style.boxSizing = 'border-box';
    });
  }

  function adjustPdfCanvas(canvas, scale, slideEl) {
    var expectedCanvasWidth = SLIDE_WIDTH * scale;
    var expectedCanvasHeight = SLIDE_HEIGHT * scale;
    var widthDiff = Math.abs(canvas.width - expectedCanvasWidth);
    var heightDiff = Math.abs(canvas.height - expectedCanvasHeight);
    if (widthDiff <= 5 && heightDiff <= 5) return canvas;
    var adjustedCanvas = createEl('canvas');
    adjustedCanvas.width = expectedCanvasWidth;
    adjustedCanvas.height = expectedCanvasHeight;
    var ctx = adjustedCanvas.getContext('2d');
    if (!ctx) return canvas;
    var bgColor = window.getComputedStyle(slideEl).backgroundColor || '#ffffff';
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, expectedCanvasWidth, expectedCanvasHeight);
    var sourceX = 0, sourceY = 0, sourceWidth = canvas.width, sourceHeight = canvas.height;
    var destX = 0, destY = 0, destWidth = expectedCanvasWidth, destHeight = expectedCanvasHeight;
    if (canvas.width > expectedCanvasWidth) {
      sourceX = (canvas.width - expectedCanvasWidth) / 2;
      sourceWidth = expectedCanvasWidth;
    } else if (canvas.width < expectedCanvasWidth) {
      destX = (expectedCanvasWidth - canvas.width) / 2;
      destWidth = canvas.width;
    }
    if (canvas.height > expectedCanvasHeight) {
      sourceY = (canvas.height - expectedCanvasHeight) / 2;
      sourceHeight = expectedCanvasHeight;
    } else if (canvas.height < expectedCanvasHeight) {
      destY = (expectedCanvasHeight - canvas.height) / 2;
      destHeight = canvas.height;
    }
    ctx.drawImage(canvas, sourceX, sourceY, sourceWidth, sourceHeight, destX, destY, destWidth, destHeight);
    return adjustedCanvas;
  }

  function inlineComputedStyles(orig, copy) {
    var cs = window.getComputedStyle(orig);
    var i;
    for (i = 0; i < cs.length; i++) {
      var prop = cs.item(i);
      copy.style.setProperty(prop, cs.getPropertyValue(prop), cs.getPropertyPriority(prop));
    }
    var origChildren = orig.children;
    var copyChildren = copy.children;
    for (i = 0; i < origChildren.length; i++) {
      inlineComputedStyles(origChildren[i], copyChildren[i]);
    }
  }

  async function rasterizeElement(slideEl, scale) {
    var clone = slideEl.cloneNode(true);
    inlineComputedStyles(slideEl, clone);
    clone.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
    var serialized = new XMLSerializer().serializeToString(clone);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + SLIDE_WIDTH +
      '" height="' + SLIDE_HEIGHT + '"><foreignObject x="0" y="0" width="100%" height="100%">' +
      serialized + '</foreignObject></svg>';
    var url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    var img = new Image();
    await new Promise(function (resolve, reject) {
      img.onload = resolve;
      img.onerror = function () { reject(new Error('SVG raster failed')); };
      img.src = url;
    });
    var canvas = createEl('canvas');
    canvas.width = SLIDE_WIDTH * scale;
    canvas.height = SLIDE_HEIGHT * scale;
    var ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('canvas context missing');
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  async function captureImage(command) {
    var pdf = !!command.applyPdfSubtitleFixes;
    var waitForChartsMs = typeof command.waitForChartsMs === 'number'
      ? command.waitForChartsMs
      : (pdf ? 5000 : 4000);
    if (pdf) {
      await sleep(1000);
      await waitForPdfCharts(waitForChartsMs);
      await sleep(300);
      document.body.offsetHeight;
      document.body.offsetHeight;
      document.documentElement.style.width = SLIDE_WIDTH + 'px';
      document.documentElement.style.height = SLIDE_HEIGHT + 'px';
      document.documentElement.style.overflow = 'hidden';
      document.documentElement.style.margin = '0';
      document.documentElement.style.padding = '0';
      document.body.style.margin = '0';
      document.body.style.padding = '0';
      document.body.style.width = SLIDE_WIDTH + 'px';
      document.body.style.height = SLIDE_HEIGHT + 'px';
      document.body.style.overflow = 'hidden';
      document.body.style.position = 'relative';
      document.body.style.boxSizing = 'border-box';
    } else {
      await sleep(300);
      await waitForScreenshotCharts(waitForChartsMs);
      try { await document.fonts.ready; } catch (e) { /* best effort */ }
      await sleep(150);
    }
    var slideEl = findSlideRoot(document);
    forceRootSize(slideEl, document);
    var subtitleMargins = [];
    if (pdf) {
      slideEl.offsetHeight;
      await sleep(400);
      document.body.offsetHeight;
      subtitleMargins = applyPdfSubtitleFixes(slideEl, window);
      slideEl.offsetHeight;
      slideEl.offsetHeight;
      await sleep(50);
      await sleep(150);
    }
    var scale = command.scale;
    var canvas;
    if (pdf) {
      pdfOnClone(document, subtitleMargins);
    }
    // html2canvas clones through a nested iframe. Nested frames inherit this
    // opaque sandbox and become a different unique origin, so the library
    // cannot read the clone document. Rasterize via SVG foreignObject in this
    // browsing context instead. The html2canvas dist is still bundled in the
    // srcdoc as required.
    canvas = await rasterizeElement(slideEl, scale);
    if (pdf) {
      canvas = adjustPdfCanvas(canvas, scale, slideEl);
    }
    var quality = typeof command.quality === 'number' ? command.quality : undefined;
    var dataUrl = quality === undefined
      ? canvas.toDataURL(command.format)
      : canvas.toDataURL(command.format, quality);
    post({
      kind: 'capture-image-result',
      requestId: command.requestId,
      dataUrl: dataUrl,
      width: canvas.width,
      height: canvas.height
    });
  }

  async function captureCanvases(command) {
    var maxWait = command.waitForChartsMs || 20000;
    var chartJsLoaded = false;
    for (var waitAttempt = 0; waitAttempt < 20; waitAttempt++) {
      if (typeof window.Chart !== 'undefined') {
        chartJsLoaded = true;
        break;
      }
      await sleep(100);
    }
    if (!chartJsLoaded) { /* Chart.js may still be absent on non-chart slides */ }
    await waitForPptxCharts(maxWait);
    await sleep(2000);
    document.body.offsetHeight;
    var chartImages = {};
    var canvases = document.querySelectorAll('canvas');
    for (var i = 0; i < canvases.length; i++) {
      var canvas = canvases[i];
      try {
        if (canvas.width === 0 || canvas.height === 0) continue;
        var ctx = canvas.getContext('2d');
        if (!ctx) continue;
        try {
          var sampleWidth = Math.min(canvas.width, 200);
          var sampleHeight = Math.min(canvas.height, 200);
          var imageData = ctx.getImageData(0, 0, sampleWidth, sampleHeight);
          var data = imageData.data;
          var pixelCount = 0;
          for (var j = 3; j < data.length; j += 4) {
            if (data[j] > 0) pixelCount++;
          }
          if (pixelCount < 100) continue;
        } catch (e) {
          continue;
        }
        var dataUrl = canvas.toDataURL('image/png');
        if (dataUrl.length < 2000) continue;
        var canvasId = canvas.id || ('chart_' + i);
        chartImages[canvasId] = dataUrl;
      } catch (error) {
        /* skip this canvas */
      }
    }
    post({
      kind: 'capture-canvases-result',
      requestId: command.requestId,
      canvases: chartImages
    });
  }

  function applyFontMode(fontMode) {
    if (fontMode === 'universal') {
      var style = createEl('style');
      style.id = 'htp-font-shim';
      style.textContent = [
        '@font-face { font-family: "Inter"; src: local("Arial"); font-display: block; }',
        '@font-face { font-family: "DM Sans"; src: local("Arial"); font-display: block; }',
        '@font-face { font-family: "DM Mono"; src: local("Consolas"); font-display: block; }',
        '@font-face { font-family: "Söhne"; src: local("Arial"); font-display: block; }',
        '@font-face { font-family: "IBM Plex Sans"; src: local("Arial"); font-display: block; }',
        '@font-face { font-family: "IBM Plex Mono"; src: local("Consolas"); font-display: block; }',
        '@font-face { font-family: "Graphik"; src: local("Arial"); font-display: block; }',
        '@font-face { font-family: "Tiempos"; src: local("Georgia"); font-display: block; }',
        'body, body * { font-family: Arial, Helvetica, sans-serif !important; }',
        'body code, body pre, body kbd, body samp,',
        'body .mono, body [class*="mono" i], body [class*="Mono"] {',
        '  font-family: Consolas, "Courier New", monospace !important;',
        '}'
      ].join('\\n');
      document.head.appendChild(style);
      var fontScript = createEl('script');
      fontScript.textContent = FONT_REWRITE_SRC;
      document.head.appendChild(fontScript);
    } else if (fontMode === 'google_slides') {
      var link = createEl('link');
      link.rel = 'stylesheet';
      link.href = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap';
      document.head.appendChild(link);
    }
  }

  async function extractRecords(command) {
    if (typeof extractSlide !== 'function') {
      throw new Error('walker missing');
    }
    applyFontMode(command.fontMode);
    try { await document.fonts.ready; } catch (e) {}
    await sleep(150);
    try { await document.fonts.ready; } catch (e) {}
    var sections = document.querySelectorAll('section.slide-container');
    var notesEl = document.getElementById('speaker-notes');
    var notesList = [];
    try {
      notesList = notesEl ? JSON.parse(notesEl.textContent || '[]') : [];
    } catch (e) {
      notesList = [];
    }
    var out = [];
    for (var i = 0; i < sections.length; i++) {
      sections.forEach(function (s, j) {
        s.style.display = j === i ? 'block' : 'none';
      });
      await sleep(SLIDE_SETTLE_MS);
      try { await document.fonts.ready; } catch (e) {}
      var root = document.querySelector('section.slide-container[data-slide-index="' + i + '"]');
      if (root && typeof prepareSlide === 'function') {
        try { await prepareSlide(root); } catch (prepErr) { /* keep walking */ }
      }
      var extract = root ? extractSlide(root) : null;
      if (!extract) continue;
      var notes = '';
      try { notes = notesList[i] || ''; } catch (e) { notes = ''; }
      out.push({
        width: extract.width,
        height: extract.height,
        records: extract.records,
        notes: notes || ''
      });
    }
    post({
      kind: 'extract-records-result',
      requestId: command.requestId,
      records: out
    });
  }

  async function onCommand(command) {
    try {
      if (command.kind === 'capture-image') {
        await captureImage(command);
      } else if (command.kind === 'capture-canvases') {
        await captureCanvases(command);
      } else if (command.kind === 'extract-records') {
        await extractRecords(command);
      } else {
        fail(command.requestId, 'INVALID_COMMAND', new Error('Unknown export command'));
      }
    } catch (err) {
      fail(command && command.requestId, 'CAPTURE_FAILED', err);
    }
  }

  addWinListener('message', function (event) {
    if (event.source !== parentWin) return;
    var data = event.data;
    if (!data || data.type !== TYPE || data.channelId !== CHANNEL_ID) return;
    if (handled) return;
    if (!data.kind || data.kind === 'ready' || data.kind === 'error') return;
    handled = true;
    onCommand(data);
  });

  function emitReady() {
    post({ kind: 'ready' });
  }
  if (document.readyState === 'complete') {
    emitReady();
  } else {
    addWinListener('load', emitReady);
  }
})();
`;

export function trustedExportRuntimeMarkup(): string {
  return [
    '<script>',
    HTML2CANVAS_SOURCE_PLACEHOLDER,
    '</script>',
    '<script>',
    escapeEmbeddedScript(WALKER_SOURCE),
    '</script>',
    '<script>',
    escapeEmbeddedScript(BOOTSTRAP_SOURCE),
    '</script>',
  ].join('\n');
}
