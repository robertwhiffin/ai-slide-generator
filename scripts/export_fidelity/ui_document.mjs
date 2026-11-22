#!/usr/bin/env node
// The UI's own slide documents, for the export fidelity harness's truth.
//
// Each slide's document is built by the UI's own code, not a copy of it:
// frontend/src/services/slideDocument.ts, bundled unchanged with the
// frontend's esbuild (frontend/node_modules, `npm ci` in frontend/) and
// imported from memory. The options are the ones the slide viewer's stage
// passes (frontend/src/components/SlideViewer/SlideStage.tsx):
//   buildSlideDocument(slide.html, {css, externalScripts, scripts: slide.scripts,
//                                   extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE})
// so the document is the one the user sees, its frame contract and root reset
// included, and a change to slideDocument.ts reaches the truth at once.
//
// usage: node ui_document.mjs <out_dir> < payload.json
//   payload: {"css": str, "externalScripts": [str], "slides": [{"name", "html", "scripts"}]}
// writes <out_dir>/<name>.html for every slide, and prints each path, once
// every document is built: a failure writes none.
// Exits 2 with one [export-fidelity] line, naming what to install, when the
// frontend's esbuild is missing or cannot build (an install without its
// platform binary loads esbuild and fails only when it builds).

import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const SLIDE_DOCUMENT_SOURCE = path.join(FRONTEND_DIR, 'src', 'services', 'slideDocument.ts');
const MISSING_EXIT_CODE = 2;

// Stops on one [export-fidelity] line naming the remedy: the frontend's
// esbuild `state` ("is not installed", "cannot build it"), and the first line
// of `error`.
function esbuildFailed(state, error) {
  console.error(
    '[export-fidelity] the UI truth bundles frontend/src/services/slideDocument.ts with the ' +
    `frontend's esbuild, which ${state}: run \`npm ci\` in frontend/ ` +
    `(${String(error && error.message).split('\n')[0]})`,
  );
  process.exit(MISSING_EXIT_CODE);
}

// The frontend's own esbuild, resolved as the frontend resolves it.
function frontendEsbuild() {
  const require = createRequire(path.join(FRONTEND_DIR, 'package.json'));
  try {
    return require('esbuild');
  } catch (error) {
    return esbuildFailed('is not installed', error);
  }
}

// slideDocument.ts as an ES module, bundled unchanged and imported from memory.
async function slideDocumentModule() {
  const esbuild = frontendEsbuild();
  let bundled;
  try {
    bundled = await esbuild.build({
      entryPoints: [SLIDE_DOCUMENT_SOURCE],
      bundle: true,
      format: 'esm',
      platform: 'neutral',
      write: false,
      logLevel: 'silent',
    });
  } catch (error) {
    return esbuildFailed('cannot build it', error);
  }
  const source = bundled.outputFiles[0].text;
  return import('data:text/javascript;base64,' + Buffer.from(source, 'utf-8').toString('base64'));
}

async function main() {
  const [outDir] = process.argv.slice(2);
  if (!outDir) {
    console.error('usage: node ui_document.mjs <out_dir> < payload.json');
    process.exit(1);
  }
  const payload = JSON.parse(fs.readFileSync(0, 'utf-8'));
  const { buildSlideDocument, SLIDE_PREVIEW_RESET_STYLE } = await slideDocumentModule();
  const documents = payload.slides.map((slide) => ({
    outPath: path.join(outDir, `${slide.name}.html`),
    html: buildSlideDocument(slide.html, {
      css: payload.css || '',
      externalScripts: payload.externalScripts || [],
      scripts: slide.scripts || '',
      extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE,
    }),
  }));
  fs.mkdirSync(outDir, { recursive: true });
  for (const document of documents) {
    fs.writeFileSync(document.outPath, document.html, 'utf-8');
    console.log(document.outPath);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
