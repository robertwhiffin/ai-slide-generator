// Records JSON -> editable PPTX bytes.
//
// Reads a JSON payload from stdin (or argv[2] if given), emits a .pptx via
// pptxgenjs. Record shape matches the scaffold reference design:
//   { slides: [ { width, height, records, notes? } ], title?, font_mode? }
// where each record is one of:
//   { kind: 'rect',  x, y, w, h, fill, stroke?, strokeW?, radius? }
//   { kind: 'image', x, y, w, h, src }   // src: dataURL or http(s)
//   { kind: 'text',  x, y, w, h, runs: [{text, bold, italic, color, size, family, breakLine?, underline?}], align, valign }
// Walker produces records in paint order (pre-order DOM walk); we emit in that
// order so stacking contexts follow the browser's behavior.
//
// Usage:
//   node emit.mjs <records.json> <out.pptx>
//   node emit.mjs - <out.pptx>   (read from stdin)

import pptxgen from 'pptxgenjs';
import fs from 'node:fs/promises';

const PX_PER_IN = 96;
const px = v => v / PX_PER_IN;

// ───── font substitution ─────────────────────────────────────────────

const UNIVERSAL_FALLBACKS = {
  'Inter':          'Arial',
  'DM Sans':        'Arial',
  'DM Mono':        'Consolas',
  'Söhne':          'Arial',
  'Tiempos':        'Georgia',
  'Graphik':        'Arial',
  'IBM Plex Sans':  'Arial',
  'IBM Plex Mono':  'Consolas',
};
const SAFE_FONTS = new Set([
  'Arial', 'Helvetica', 'Georgia', 'Times New Roman', 'Calibri', 'Cambria',
  'Verdana', 'Consolas', 'Courier New', 'Tahoma',
]);

function substituteFont(family, mode) {
  if (!family) return mode === 'universal' ? 'Arial' : 'DM Sans';
  if (mode !== 'universal') return family;
  return UNIVERSAL_FALLBACKS[family] || (SAFE_FONTS.has(family) ? family : 'Arial');
}

// ───── emitter ───────────────────────────────────────────────────────

export async function emitPptx(slides, outPath, fontMode = 'universal', title = 'slides') {
  const pptx = new pptxgen();
  const first = slides[0];
  pptx.defineLayout({ name: 'CUSTOM', width: px(first.width), height: px(first.height) });
  pptx.layout = 'CUSTOM';
  pptx.title = title;

  for (const slide of slides) {
    const s = pptx.addSlide();
    if (slide.notes) s.addNotes(slide.notes);
    for (const r of slide.records || []) {
      if (r.kind === 'rect') emitRect(s, r);
      else if (r.kind === 'image') emitImage(s, r);
      else if (r.kind === 'text') emitText(s, r, fontMode);
    }
  }

  await pptx.writeFile({ fileName: outPath });
}

function emitRect(s, r) {
  const opts = {
    x: px(r.x), y: px(r.y), w: px(r.w), h: px(r.h),
    fill: r.fill ? { color: r.fill } : { type: 'none' },
    line: r.stroke && (r.strokeW || 0) >= 0.5
      ? { color: r.stroke, width: r.strokeW }
      : { type: 'none' },
  };
  if (r.radius > 0) {
    // pptxgenjs rectRadius is a factor 0..0.5 of min(w,h).
    opts.rectRadius = Math.min(0.5, r.radius / Math.min(r.w, r.h));
    s.addShape('roundRect', opts);
  } else {
    s.addShape('rect', opts);
  }
}

function emitImage(s, r) {
  const opts = { x: px(r.x), y: px(r.y), w: px(r.w), h: px(r.h) };
  if (typeof r.src === 'string' && r.src.startsWith('data:')) {
    opts.data = r.src;
  } else if (r.src) {
    opts.path = r.src;
  } else {
    return;
  }
  s.addImage(opts);
}

function emitText(s, r, fontMode) {
  const textArr = (r.runs || [])
    .filter(run => run.text || run.breakLine)
    .map(run => ({
      text: run.text || '',
      options: {
        bold: !!run.bold,
        italic: !!run.italic,
        underline: run.underline ? { style: 'sng' } : undefined,
        color: run.color,
        fontFace: substituteFont(run.family, fontMode),
        fontSize: (run.size || 14) * 0.75,  // CSS px → pt
        breakLine: !!run.breakLine,
      },
    }));
  if (!textArr.length) return;

  s.addText(textArr, {
    x: px(r.x),
    y: px(r.y),
    // +2px slack to absorb sub-pixel rounding between browser layout and
    // PPT's line-break algorithm — without it, the last word on a line
    // often pushes to the next line.
    w: px(r.w + 2),
    h: px(r.h + 2),
    align: r.align || 'left',
    valign: r.valign || 'top',
    margin: 0,
    // CRITICAL: disable autoFit so PPT doesn't normAutofit-shrink text
    // unpredictably. The walker measured the box; trust the measurement.
    autoFit: false,
    fit: 'none',
    wrap: true,
  });
}

// ───── main ──────────────────────────────────────────────────────────

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf-8');
}

const [, , inputArg, outArg] = process.argv;
if (!outArg) {
  console.error('Usage: node emit.mjs <records.json|-> <out.pptx>');
  process.exit(1);
}

const raw = (!inputArg || inputArg === '-')
  ? await readStdin()
  : await fs.readFile(inputArg, 'utf-8');

let payload;
try {
  payload = JSON.parse(raw);
} catch (e) {
  console.error('[pptx-emit] invalid JSON payload:', e.message);
  process.exit(2);
}

const slides = payload.slides || [];
if (!slides.length) {
  console.error('[pptx-emit] no slides in payload');
  process.exit(3);
}

await emitPptx(
  slides,
  outArg,
  payload.font_mode || 'universal',
  payload.title || 'slides',
);
console.error(`[pptx-emit] wrote ${outArg} (${slides.length} slides)`);
