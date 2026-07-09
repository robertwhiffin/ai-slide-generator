/**
 * html2pptx - Convert HTML slide to pptxgenjs slide with positioned elements
 *
 * USAGE:
 *   const pptx = new pptxgen();
 *   pptx.layout = 'LAYOUT_16x9';  // Must match HTML body dimensions
 *
 *   const { slide, placeholders } = await html2pptx('slide.html', pptx);
 *   slide.addChart(pptx.charts.LINE, data, placeholders[0]);
 *
 *   await pptx.writeFile('output.pptx');
 *
 * FEATURES:
 *   - Converts HTML to PowerPoint with accurate positioning
 *   - Supports text, images, shapes, and bullet lists
 *   - Extracts placeholder elements (class="placeholder") with positions
 *   - Handles CSS gradients, borders, and margins
 *
 * VALIDATION:
 *   - Uses body width/height from HTML for viewport sizing
 *   - Throws error if HTML dimensions don't match presentation layout
 *   - Throws error if content overflows body (with overflow details)
 *
 * RETURNS:
 *   { slide, placeholders } where placeholders is an array of { id, x, y, w, h }
 */

const { chromium } = require('playwright');
const path = require('path');

const PT_PER_PX = 0.75;
const PX_PER_IN = 96;
const EMU_PER_IN = 914400;

// Helper: Get body dimensions and check for overflow
async function getBodyDimensions(page) {
  const bodyDimensions = await page.evaluate(() => {
    const body = document.body;
    const style = window.getComputedStyle(body);

    return {
      width: parseFloat(style.width),
      height: parseFloat(style.height),
      scrollWidth: body.scrollWidth,
      scrollHeight: body.scrollHeight
    };
  });

  const errors = [];
  // Tellr-soften: tolerance bumped from 1px to 100px (~75pt) because Tellr
  // LLM-generated decks consistently overflow body by ~80px (footer / extra
  // section). Visually clipped by `overflow: hidden`, but huashu's
  // scrollHeight check still flags it. Keep the warn behavior, but only
  // fail when overflow is dramatic (>100px = obvious authoring bug).
  const TELLR_OVERFLOW_TOLERANCE_PX = 100;
  const widthOverflowPx = Math.max(0, bodyDimensions.scrollWidth - bodyDimensions.width - TELLR_OVERFLOW_TOLERANCE_PX);
  const heightOverflowPx = Math.max(0, bodyDimensions.scrollHeight - bodyDimensions.height - TELLR_OVERFLOW_TOLERANCE_PX);

  const widthOverflowPt = widthOverflowPx * PT_PER_PX;
  const heightOverflowPt = heightOverflowPx * PT_PER_PX;

  if (widthOverflowPt > 0 || heightOverflowPt > 0) {
    const directions = [];
    if (widthOverflowPt > 0) directions.push(`${widthOverflowPt.toFixed(1)}pt horizontally`);
    if (heightOverflowPt > 0) directions.push(`${heightOverflowPt.toFixed(1)}pt vertically`);
    const reminder = heightOverflowPt > 0 ? ' (Remember: leave 0.5" margin at bottom of slide)' : '';
    errors.push(`HTML content overflows body by ${directions.join(' and ')}${reminder}`);
  }

  return { ...bodyDimensions, errors };
}

// Helper: Validate dimensions match presentation layout
function validateDimensions(bodyDimensions, pres) {
  const errors = [];
  const widthInches = bodyDimensions.width / PX_PER_IN;
  const heightInches = bodyDimensions.height / PX_PER_IN;

  if (pres.presLayout) {
    const layoutWidth = pres.presLayout.width / EMU_PER_IN;
    const layoutHeight = pres.presLayout.height / EMU_PER_IN;

    if (Math.abs(layoutWidth - widthInches) > 0.1 || Math.abs(layoutHeight - heightInches) > 0.1) {
      errors.push(
        `HTML dimensions (${widthInches.toFixed(1)}" × ${heightInches.toFixed(1)}") ` +
        `don't match presentation layout (${layoutWidth.toFixed(1)}" × ${layoutHeight.toFixed(1)}")`
      );
    }
  }
  return errors;
}

function validateTextBoxPosition(slideData, bodyDimensions) {
  const errors = [];
  const slideHeightInches = bodyDimensions.height / PX_PER_IN;
  const minBottomMargin = 0.5; // 0.5 inches from bottom

  for (const el of slideData.elements) {
    // Check text elements (p, h1-h6, list)
    if (['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'list'].includes(el.type)) {
      const fontSize = el.style?.fontSize || 0;
      const bottomEdge = el.position.y + el.position.h;
      const distanceFromBottom = slideHeightInches - bottomEdge;

      if (fontSize > 12 && distanceFromBottom < minBottomMargin) {
        const getText = () => {
          if (typeof el.text === 'string') return el.text;
          if (Array.isArray(el.text)) return el.text.find(t => t.text)?.text || '';
          if (Array.isArray(el.items)) return el.items.find(item => item.text)?.text || '';
          return '';
        };
        const textPrefix = getText().substring(0, 50) + (getText().length > 50 ? '...' : '');

        errors.push(
          `Text box "${textPrefix}" ends too close to bottom edge ` +
          `(${distanceFromBottom.toFixed(2)}" from bottom, minimum ${minBottomMargin}" required)`
        );
      }
    }
  }

  return errors;
}

// Helper: Add background to slide
async function addBackground(slideData, targetSlide, tmpDir) {
  if (slideData.background.type === 'image' && slideData.background.path) {
    const src = slideData.background.path;
    // Tellr-soften: pptxgenjs slide.background takes `data:` for data URLs
    // and `path:` for filesystem paths. The vanilla huashu code always
    // assigned to path, which silently drops the bg when src is a base64
    // data URL (e.g., our preprocessor's rasterized gradient).
    if (src.startsWith('data:')) {
      targetSlide.background = { data: src };
    } else if (src.startsWith('file://')) {
      targetSlide.background = { path: src.replace('file://', '') };
    } else {
      targetSlide.background = { path: src };
    }
  } else if (slideData.background.type === 'color' && slideData.background.value) {
    targetSlide.background = { color: slideData.background.value };
  }
}

// Helper: Add elements to slide
function addElements(slideData, targetSlide, pres) {
  for (const el of slideData.elements) {
    if (el.type === 'image') {
      // Tellr-soften: pptxgenjs needs `data:` for data-URL sources and
      // `path:` for filesystem paths. The vanilla huashu code always
      // assigned to `path`, which caused "Unable to read media" when a
      // <canvas> was rasterized to a base64 dataURL by our preprocessor.
      const imageOpts = {
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h
      };
      if (typeof el.src === 'string' && el.src.startsWith('data:')) {
        imageOpts.data = el.src;
      } else {
        imageOpts.path = el.src.startsWith('file://') ? el.src.replace('file://', '') : el.src;
      }
      targetSlide.addImage(imageOpts);
    } else if (el.type === 'line') {
      targetSlide.addShape(pres.ShapeType.line, {
        x: el.x1,
        y: el.y1,
        w: el.x2 - el.x1,
        h: el.y2 - el.y1,
        line: { color: el.color, width: el.width }
      });
    } else if (el.type === 'shape') {
      const shapeOptions = {
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h,
        shape: el.shape.rectRadius > 0 ? pres.ShapeType.roundRect : pres.ShapeType.rect
      };

      if (el.shape.fill) {
        shapeOptions.fill = { color: el.shape.fill };
        if (el.shape.transparency != null) shapeOptions.fill.transparency = el.shape.transparency;
      }
      if (el.shape.line) shapeOptions.line = el.shape.line;
      if (el.shape.rectRadius > 0) shapeOptions.rectRadius = el.shape.rectRadius;
      if (el.shape.shadow) shapeOptions.shadow = el.shape.shadow;

      targetSlide.addText(el.text || '', shapeOptions);
    } else if (el.type === 'list') {
      const listOptions = {
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h,
        fontSize: el.style.fontSize,
        fontFace: el.style.fontFace,
        color: el.style.color,
        align: el.style.align,
        valign: 'top',
        lineSpacing: el.style.lineSpacing,
        paraSpaceBefore: el.style.paraSpaceBefore,
        paraSpaceAfter: el.style.paraSpaceAfter,
        margin: el.style.margin
      };
      if (el.style.margin) listOptions.margin = el.style.margin;
      targetSlide.addText(el.items, listOptions);
    } else {
      // Check if text is single-line (height suggests one line)
      const lineHeight = el.style.lineSpacing || el.style.fontSize * 1.2;
      const isSingleLine = el.position.h <= lineHeight * 1.5;

      let adjustedX = el.position.x;
      let adjustedW = el.position.w;

      // Make single-line text 2% wider to account for underestimate
      if (isSingleLine) {
        const widthIncrease = el.position.w * 0.02;
        const align = el.style.align;

        if (align === 'center') {
          // Center: expand both sides
          adjustedX = el.position.x - (widthIncrease / 2);
          adjustedW = el.position.w + widthIncrease;
        } else if (align === 'right') {
          // Right: expand to the left
          adjustedX = el.position.x - widthIncrease;
          adjustedW = el.position.w + widthIncrease;
        } else {
          // Left (default): expand to the right
          adjustedW = el.position.w + widthIncrease;
        }
      }

      const textOptions = {
        x: adjustedX,
        y: el.position.y,
        w: adjustedW,
        h: el.position.h,
        fontSize: el.style.fontSize,
        fontFace: el.style.fontFace,
        color: el.style.color,
        bold: el.style.bold,
        italic: el.style.italic,
        underline: el.style.underline,
        // Tellr-soften: anchor text vertically to MIDDLE of frame (was 'top')
        // so badge inner text lines up with plain-text cells on the same
        // row baseline. Frame heights are measured-from-bbox, so this
        // centers the text within the measured area.
        valign: 'middle',
        lineSpacing: el.style.lineSpacing,
        paraSpaceBefore: el.style.paraSpaceBefore,
        paraSpaceAfter: el.style.paraSpaceAfter,
        inset: 0  // Remove default PowerPoint internal padding
      };

      if (el.style.align) textOptions.align = el.style.align;
      if (el.style.margin) textOptions.margin = el.style.margin;
      if (el.style.rotate !== undefined) textOptions.rotate = el.style.rotate;
      if (el.style.transparency !== null && el.style.transparency !== undefined) textOptions.transparency = el.style.transparency;

      targetSlide.addText(el.text, textOptions);
    }
  }
}

// Helper: Extract slide data from HTML page
async function extractSlideData(page) {
  return await page.evaluate(() => {
    const PT_PER_PX = 0.75;
    const PX_PER_IN = 96;

    // Fonts that are single-weight and should not have bold applied
    // (applying bold causes PowerPoint to use faux bold which makes text wider)
    const SINGLE_WEIGHT_FONTS = ['impact'];

    // Helper: Check if a font should skip bold formatting
    const shouldSkipBold = (fontFamily) => {
      if (!fontFamily) return false;
      const normalizedFont = fontFamily.toLowerCase().replace(/['"]/g, '').split(',')[0].trim();
      return SINGLE_WEIGHT_FONTS.includes(normalizedFont);
    };

    // Unit conversion helpers
    const pxToInch = (px) => px / PX_PER_IN;
    const pxToPoints = (pxStr) => parseFloat(pxStr) * PT_PER_PX;
    const rgbToHex = (rgbStr) => {
      // Handle transparent backgrounds by defaulting to white
      if (rgbStr === 'rgba(0, 0, 0, 0)' || rgbStr === 'transparent') return 'FFFFFF';

      const match = rgbStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (!match) return 'FFFFFF';
      return match.slice(1).map(n => parseInt(n).toString(16).padStart(2, '0')).join('');
    };

    const extractAlpha = (rgbStr) => {
      const match = rgbStr.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
      if (!match || !match[4]) return null;
      const alpha = parseFloat(match[4]);
      return Math.round((1 - alpha) * 100);
    };

    const applyTextTransform = (text, textTransform) => {
      if (textTransform === 'uppercase') return text.toUpperCase();
      if (textTransform === 'lowercase') return text.toLowerCase();
      if (textTransform === 'capitalize') {
        return text.replace(/\b\w/g, c => c.toUpperCase());
      }
      return text;
    };

    // Extract rotation angle from CSS transform and writing-mode
    const getRotation = (transform, writingMode) => {
      let angle = 0;

      // Handle writing-mode first
      // PowerPoint: 90° = text rotated 90° clockwise (reads top to bottom, letters upright)
      // PowerPoint: 270° = text rotated 270° clockwise (reads bottom to top, letters upright)
      if (writingMode === 'vertical-rl') {
        // vertical-rl alone = text reads top to bottom = 90° in PowerPoint
        angle = 90;
      } else if (writingMode === 'vertical-lr') {
        // vertical-lr alone = text reads bottom to top = 270° in PowerPoint
        angle = 270;
      }

      // Then add any transform rotation
      if (transform && transform !== 'none') {
        // Try to match rotate() function
        const rotateMatch = transform.match(/rotate\((-?\d+(?:\.\d+)?)deg\)/);
        if (rotateMatch) {
          angle += parseFloat(rotateMatch[1]);
        } else {
          // Browser may compute as matrix - extract rotation from matrix
          const matrixMatch = transform.match(/matrix\(([^)]+)\)/);
          if (matrixMatch) {
            const values = matrixMatch[1].split(',').map(parseFloat);
            // matrix(a, b, c, d, e, f) where rotation = atan2(b, a)
            const matrixAngle = Math.atan2(values[1], values[0]) * (180 / Math.PI);
            angle += Math.round(matrixAngle);
          }
        }
      }

      // Normalize to 0-359 range
      angle = angle % 360;
      if (angle < 0) angle += 360;

      return angle === 0 ? null : angle;
    };

    // Get position/dimensions accounting for rotation
    const getPositionAndSize = (el, rect, rotation) => {
      if (rotation === null) {
        return { x: rect.left, y: rect.top, w: rect.width, h: rect.height };
      }

      // For 90° or 270° rotations, swap width and height
      // because PowerPoint applies rotation to the original (unrotated) box
      const isVertical = rotation === 90 || rotation === 270;

      if (isVertical) {
        // The browser shows us the rotated dimensions (tall box for vertical text)
        // But PowerPoint needs the pre-rotation dimensions (wide box that will be rotated)
        // So we swap: browser's height becomes PPT's width, browser's width becomes PPT's height
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        return {
          x: centerX - rect.height / 2,
          y: centerY - rect.width / 2,
          w: rect.height,
          h: rect.width
        };
      }

      // For other rotations, use element's offset dimensions
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      return {
        x: centerX - el.offsetWidth / 2,
        y: centerY - el.offsetHeight / 2,
        w: el.offsetWidth,
        h: el.offsetHeight
      };
    };

    // Parse CSS box-shadow into PptxGenJS shadow properties
    const parseBoxShadow = (boxShadow) => {
      if (!boxShadow || boxShadow === 'none') return null;

      // Browser computed style format: "rgba(0, 0, 0, 0.3) 2px 2px 8px 0px [inset]"
      // CSS format: "[inset] 2px 2px 8px 0px rgba(0, 0, 0, 0.3)"

      const insetMatch = boxShadow.match(/inset/);

      // IMPORTANT: PptxGenJS/PowerPoint doesn't properly support inset shadows
      // Only process outer shadows to avoid file corruption
      if (insetMatch) return null;

      // Extract color first (rgba or rgb at start)
      const colorMatch = boxShadow.match(/rgba?\([^)]+\)/);

      // Extract numeric values (handles both px and pt units)
      const parts = boxShadow.match(/([-\d.]+)(px|pt)/g);

      if (!parts || parts.length < 2) return null;

      const offsetX = parseFloat(parts[0]);
      const offsetY = parseFloat(parts[1]);
      const blur = parts.length > 2 ? parseFloat(parts[2]) : 0;

      // Calculate angle from offsets (in degrees, 0 = right, 90 = down)
      let angle = 0;
      if (offsetX !== 0 || offsetY !== 0) {
        angle = Math.atan2(offsetY, offsetX) * (180 / Math.PI);
        if (angle < 0) angle += 360;
      }

      // Calculate offset distance (hypotenuse)
      const offset = Math.sqrt(offsetX * offsetX + offsetY * offsetY) * PT_PER_PX;

      // Extract opacity from rgba
      let opacity = 0.5;
      if (colorMatch) {
        const opacityMatch = colorMatch[0].match(/[\d.]+\)$/);
        if (opacityMatch) {
          opacity = parseFloat(opacityMatch[0].replace(')', ''));
        }
      }

      return {
        type: 'outer',
        angle: Math.round(angle),
        blur: blur * 0.75, // Convert to points
        color: colorMatch ? rgbToHex(colorMatch[0]) : '000000',
        offset: offset,
        opacity
      };
    };

    // Parse inline formatting tags (<b>, <i>, <u>, <strong>, <em>, <span>) into text runs
    const parseInlineFormatting = (element, baseOptions = {}, runs = [], baseTextTransform = (x) => x) => {
      let prevNodeIsText = false;

      element.childNodes.forEach((node) => {
        let textTransform = baseTextTransform;

        const isText = node.nodeType === Node.TEXT_NODE || node.tagName === 'BR';
        if (isText) {
          if (node.tagName === 'BR') {
            // Tellr-soften: BR → mark the PREVIOUS run with breakLine so
            // pptxgenjs inserts an inline <a:br/> after it. The vanilla
            // huashu code merged "\n" into the previous run text, which
            // pptxgenjs splits into separate <a:p> paragraphs, each
            // getting paraSpaceAfter applied — overflowing multi-line
            // headings. Marking the prior run keeps everything in one
            // paragraph (no per-line spacing) but inserts a real line
            // break visually. Empty placeholder run as fallback when BR
            // is the very first child (no prior run to mark).
            if (runs.length > 0) {
              runs[runs.length - 1].options.breakLine = true;
            } else {
              runs.push({ text: ' ', options: { ...baseOptions, breakLine: true } });
            }
            prevNodeIsText = false;  // next text starts a fresh run
            return;
          }
          const text = textTransform(node.textContent.replace(/\s+/g, ' '));
          const prevRun = runs[runs.length - 1];
          if (prevNodeIsText && prevRun) {
            prevRun.text += text;
          } else {
            runs.push({ text, options: { ...baseOptions } });
          }

        } else if (node.nodeType === Node.ELEMENT_NODE && node.textContent.trim()) {
          const options = { ...baseOptions };
          const computed = window.getComputedStyle(node);

          // Handle inline elements with computed styles
          if (node.tagName === 'SPAN' || node.tagName === 'B' || node.tagName === 'STRONG' || node.tagName === 'I' || node.tagName === 'EM' || node.tagName === 'U') {
            const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;
            if (isBold && !shouldSkipBold(computed.fontFamily)) options.bold = true;
            if (computed.fontStyle === 'italic') options.italic = true;
            if (computed.textDecoration && computed.textDecoration.includes('underline')) options.underline = true;
            if (computed.color && computed.color !== 'rgb(0, 0, 0)') {
              options.color = rgbToHex(computed.color);
              const transparency = extractAlpha(computed.color);
              if (transparency !== null) options.transparency = transparency;
            }
            if (computed.fontSize) options.fontSize = pxToPoints(computed.fontSize);

            // Apply text-transform on the span element itself
            if (computed.textTransform && computed.textTransform !== 'none') {
              const transformStr = computed.textTransform;
              textTransform = (text) => applyTextTransform(text, transformStr);
            }

            // Validate: Check for margins on inline elements
            if (computed.marginLeft && parseFloat(computed.marginLeft) > 0) {
              errors.push(`Inline element <${node.tagName.toLowerCase()}> has margin-left which is not supported in PowerPoint. Remove margin from inline elements.`);
            }
            if (computed.marginRight && parseFloat(computed.marginRight) > 0) {
              errors.push(`Inline element <${node.tagName.toLowerCase()}> has margin-right which is not supported in PowerPoint. Remove margin from inline elements.`);
            }
            if (computed.marginTop && parseFloat(computed.marginTop) > 0) {
              errors.push(`Inline element <${node.tagName.toLowerCase()}> has margin-top which is not supported in PowerPoint. Remove margin from inline elements.`);
            }
            if (computed.marginBottom && parseFloat(computed.marginBottom) > 0) {
              errors.push(`Inline element <${node.tagName.toLowerCase()}> has margin-bottom which is not supported in PowerPoint. Remove margin from inline elements.`);
            }

            // Recursively process the child node. This will flatten nested spans into multiple runs.
            parseInlineFormatting(node, options, runs, textTransform);
          }
        }

        prevNodeIsText = isText;
      });

      // Trim leading space from first run and trailing space from last run
      if (runs.length > 0) {
        runs[0].text = runs[0].text.replace(/^\s+/, '');
        runs[runs.length - 1].text = runs[runs.length - 1].text.replace(/\s+$/, '');
      }

      return runs.filter(r => r.text.length > 0);
    };

    // Extract background from body (image or color)
    const body = document.body;
    const bodyStyle = window.getComputedStyle(body);
    const bgImage = bodyStyle.backgroundImage;
    const bgColor = bodyStyle.backgroundColor;

    // Collect validation errors
    const errors = [];

    // Tellr-soften: gradients on body bg are warned-then-converted to first
    // stop solid color further down. Don't push to errors; the slide still
    // renders, just without the gradient sweep.
    if (bgImage && (bgImage.includes('linear-gradient') || bgImage.includes('radial-gradient'))) {
      console.warn('[html2pptx] CSS gradient on body — using first stop as solid fallback');
    }

    let background;
    if (bgImage && bgImage !== 'none') {
      // Extract URL from url("...") or url(...)
      const urlMatch = bgImage.match(/url\(["']?([^"')]+)["']?\)/);
      if (urlMatch) {
        background = {
          type: 'image',
          path: urlMatch[1]
        };
      } else {
        background = {
          type: 'color',
          value: rgbToHex(bgColor)
        };
      }
    } else {
      background = {
        type: 'color',
        value: rgbToHex(bgColor)
      };
    }

    // Process all elements
    const elements = [];
    const placeholders = [];
    const textTags = ['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'LI'];
    const processed = new Set();

    document.querySelectorAll('*').forEach((el) => {
      if (processed.has(el)) return;

      // Validate text elements don't have backgrounds, borders, or shadows
      if (textTags.includes(el.tagName)) {
        const computed = window.getComputedStyle(el);
        const hasBg = computed.backgroundColor && computed.backgroundColor !== 'rgba(0, 0, 0, 0)';
        const hasBorder = (computed.borderWidth && parseFloat(computed.borderWidth) > 0) ||
                          (computed.borderTopWidth && parseFloat(computed.borderTopWidth) > 0) ||
                          (computed.borderRightWidth && parseFloat(computed.borderRightWidth) > 0) ||
                          (computed.borderBottomWidth && parseFloat(computed.borderBottomWidth) > 0) ||
                          (computed.borderLeftWidth && parseFloat(computed.borderLeftWidth) > 0);
        const hasShadow = computed.boxShadow && computed.boxShadow !== 'none';

        if (hasBg || hasBorder || hasShadow) {
          errors.push(
            `Text element <${el.tagName.toLowerCase()}> has ${hasBg ? 'background' : hasBorder ? 'border' : 'shadow'}. ` +
            'Backgrounds, borders, and shadows are only supported on <div> elements, not text elements.'
          );
          return;
        }
      }

      // Extract placeholder elements (for charts, etc.)
      // Tellr-soften: el.className is only a string on HTML elements — on
      // SVG elements it's an SVGAnimatedString with no .includes, which
      // threw here and silently dropped the whole slide. getAttribute is
      // string-or-null on every element type.
      const elClassName = el.getAttribute('class') || '';
      if (elClassName.includes('placeholder')) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
          errors.push(
            `Placeholder "${el.id || 'unnamed'}" has ${rect.width === 0 ? 'width: 0' : 'height: 0'}. Check the layout CSS.`
          );
        } else {
          placeholders.push({
            id: el.id || `placeholder-${placeholders.length}`,
            x: pxToInch(rect.left),
            y: pxToInch(rect.top),
            w: pxToInch(rect.width),
            h: pxToInch(rect.height)
          });
        }
        processed.add(el);
        return;
      }

      // Extract images
      if (el.tagName === 'IMG') {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          elements.push({
            type: 'image',
            src: el.src,
            position: {
              x: pxToInch(rect.left),
              y: pxToInch(rect.top),
              w: pxToInch(rect.width),
              h: pxToInch(rect.height)
            }
          });
          processed.add(el);
          return;
        }
      }

      // Extract DIVs with backgrounds/borders as shapes
      const isContainer = el.tagName === 'DIV' && !textTags.includes(el.tagName);
      if (isContainer) {
        const computed = window.getComputedStyle(el);
        const hasBg = computed.backgroundColor && computed.backgroundColor !== 'rgba(0, 0, 0, 0)';

        // Tellr-soften: pre-processor wraps bare div text in <p>; anything
        // it missed (e.g. dynamically-injected nodes) is silently dropped
        // from the export with a console warning instead of throwing.
        for (const node of el.childNodes) {
          if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent.trim();
            if (text) {
              console.warn(`[html2pptx] dropping unwrapped div text: "${text.substring(0, 60)}"`);
            }
          }
        }

        // Tellr-soften: pre-processor replaces bg-image divs with <img>
        // children; gradients still hit this branch (the preprocessor
        // skips them). Treat as warning — div will export without the
        // gradient backdrop but its content still renders.
        const bgImage = computed.backgroundImage;
        if (bgImage && bgImage !== 'none') {
          console.warn(`[html2pptx] dropping bg-image on div: ${bgImage.substring(0, 80)}`);
        }

        // Check for borders - both uniform and partial
        const borderTop = computed.borderTopWidth;
        const borderRight = computed.borderRightWidth;
        const borderBottom = computed.borderBottomWidth;
        const borderLeft = computed.borderLeftWidth;
        const borders = [borderTop, borderRight, borderBottom, borderLeft].map(b => parseFloat(b) || 0);
        const hasBorder = borders.some(b => b > 0);
        const hasUniformBorder = hasBorder && borders.every(b => b === borders[0]);
        const borderLines = [];

        if (hasBorder && !hasUniformBorder) {
          const rect = el.getBoundingClientRect();
          const x = pxToInch(rect.left);
          const y = pxToInch(rect.top);
          const w = pxToInch(rect.width);
          const h = pxToInch(rect.height);

          // Collect lines to add after shape (inset by half the line width to center on edge)
          if (parseFloat(borderTop) > 0) {
            const widthPt = pxToPoints(borderTop);
            const inset = (widthPt / 72) / 2; // Convert points to inches, then half
            borderLines.push({
              type: 'line',
              x1: x, y1: y + inset, x2: x + w, y2: y + inset,
              width: widthPt,
              color: rgbToHex(computed.borderTopColor)
            });
          }
          if (parseFloat(borderRight) > 0) {
            const widthPt = pxToPoints(borderRight);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x + w - inset, y1: y, x2: x + w - inset, y2: y + h,
              width: widthPt,
              color: rgbToHex(computed.borderRightColor)
            });
          }
          if (parseFloat(borderBottom) > 0) {
            const widthPt = pxToPoints(borderBottom);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x, y1: y + h - inset, x2: x + w, y2: y + h - inset,
              width: widthPt,
              color: rgbToHex(computed.borderBottomColor)
            });
          }
          if (parseFloat(borderLeft) > 0) {
            const widthPt = pxToPoints(borderLeft);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x + inset, y1: y, x2: x + inset, y2: y + h,
              width: widthPt,
              color: rgbToHex(computed.borderLeftColor)
            });
          }
        }

        if (hasBg || hasBorder) {
          const rect = el.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            const shadow = parseBoxShadow(computed.boxShadow);

            // Only add shape if there's background or uniform border
            if (hasBg || hasUniformBorder) {
              elements.push({
                type: 'shape',
                text: '',  // Shape only - child text elements render on top
                position: {
                  x: pxToInch(rect.left),
                  y: pxToInch(rect.top),
                  w: pxToInch(rect.width),
                  h: pxToInch(rect.height)
                },
                shape: {
                  fill: hasBg ? rgbToHex(computed.backgroundColor) : null,
                  transparency: hasBg ? extractAlpha(computed.backgroundColor) : null,
                  line: hasUniformBorder ? {
                    color: rgbToHex(computed.borderColor),
                    width: pxToPoints(computed.borderWidth)
                  } : null,
                  // Convert border-radius to rectRadius (in inches)
                  // % values: 50%+ = circle (1), <50% = percentage of min dimension
                  // pt values: divide by 72 (72pt = 1 inch)
                  // px values: divide by 96 (96px = 1 inch)
                  rectRadius: (() => {
                    const radius = computed.borderRadius;
                    const radiusValue = parseFloat(radius);
                    if (radiusValue === 0) return 0;

                    if (radius.includes('%')) {
                      if (radiusValue >= 50) return 1;
                      // Calculate percentage of smaller dimension
                      const minDim = Math.min(rect.width, rect.height);
                      return (radiusValue / 100) * pxToInch(minDim);
                    }

                    if (radius.includes('pt')) return radiusValue / 72;
                    return radiusValue / PX_PER_IN;
                  })(),
                  shadow: shadow
                }
              });
            }

            // Add partial border lines
            elements.push(...borderLines);

            processed.add(el);
            return;
          }
        }
      }

      // Extract bullet lists as single text block
      if (el.tagName === 'UL' || el.tagName === 'OL') {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        const liElements = Array.from(el.querySelectorAll('li'));
        const items = [];
        const ulComputed = window.getComputedStyle(el);
        const ulPaddingLeftPt = pxToPoints(ulComputed.paddingLeft);

        // Split: margin-left for bullet position, indent for text position
        // margin-left + indent = ul padding-left
        const marginLeft = ulPaddingLeftPt * 0.5;
        const textIndent = ulPaddingLeftPt * 0.5;

        liElements.forEach((li, idx) => {
          const isLast = idx === liElements.length - 1;
          const runs = parseInlineFormatting(li, { breakLine: false });
          // Clean manual bullets from first run
          if (runs.length > 0) {
            runs[0].text = runs[0].text.replace(/^[•\-\*▪▸]\s*/, '');
            runs[0].options.bullet = { indent: textIndent };
          }
          // Set breakLine on last run
          if (runs.length > 0 && !isLast) {
            runs[runs.length - 1].options.breakLine = true;
          }
          items.push(...runs);
        });

        const computed = window.getComputedStyle(liElements[0] || el);

        elements.push({
          type: 'list',
          items: items,
          position: {
            x: pxToInch(rect.left),
            y: pxToInch(rect.top),
            w: pxToInch(rect.width),
            h: pxToInch(rect.height)
          },
          style: {
            fontSize: pxToPoints(computed.fontSize),
            fontFace: computed.fontFamily.split(',')[0].replace(/['"]/g, '').trim(),
            color: rgbToHex(computed.color),
            transparency: extractAlpha(computed.color),
            align: computed.textAlign === 'start' ? 'left' : computed.textAlign,
            lineSpacing: computed.lineHeight && computed.lineHeight !== 'normal' ? pxToPoints(computed.lineHeight) : null,
            paraSpaceBefore: 0,
            paraSpaceAfter: pxToPoints(computed.marginBottom),
            // PptxGenJS margin array is [left, right, bottom, top]
            margin: [marginLeft, 0, 0, 0]
          }
        });

        liElements.forEach(li => processed.add(li));
        processed.add(el);
        return;
      }

      // Extract text elements (P, H1, H2, etc.)
      if (!textTags.includes(el.tagName)) return;

      const rect = el.getBoundingClientRect();
      const text = el.textContent.trim();
      if (rect.width === 0 || rect.height === 0 || !text) return;

      // Validate: Check for manual bullet symbols in text elements (not in lists)
      if (el.tagName !== 'LI' && /^[•\-\*▪▸○●◆◇■□]\s/.test(text.trimStart())) {
        errors.push(
          `Text element <${el.tagName.toLowerCase()}> starts with bullet symbol "${text.substring(0, 20)}...". ` +
          'Use <ul> or <ol> lists instead of manual bullet symbols.'
        );
        return;
      }

      const computed = window.getComputedStyle(el);
      const rotation = getRotation(computed.transform, computed.writingMode);
      const { x, y, w, h } = getPositionAndSize(el, rect, rotation);

      const baseStyle = {
        fontSize: pxToPoints(computed.fontSize),
        fontFace: computed.fontFamily.split(',')[0].replace(/['"]/g, '').trim(),
        color: rgbToHex(computed.color),
        align: computed.textAlign === 'start' ? 'left' : computed.textAlign,
        lineSpacing: pxToPoints(computed.lineHeight),
        // Tellr-soften: paraSpaceBefore/After were set from the element's
        // CSS margin-top/bottom, but margins are already accounted for in
        // getBoundingClientRect (the next sibling's bbox starts AFTER our
        // margin). Re-applying them per-paragraph in pptxgenjs causes
        // overflow when an h2/h3/p has multiple paragraphs from <br>:
        // each para gets the spacing, blowing past the text frame's
        // measured height. Set to 0 — the bbox already has correct
        // outer spacing.
        paraSpaceBefore: 0,
        paraSpaceAfter: 0,
        // PptxGenJS margin array is [left, right, bottom, top] (not [top, right, bottom, left] as documented)
        margin: [
          pxToPoints(computed.paddingLeft),
          pxToPoints(computed.paddingRight),
          pxToPoints(computed.paddingBottom),
          pxToPoints(computed.paddingTop)
        ]
      };

      const transparency = extractAlpha(computed.color);
      if (transparency !== null) baseStyle.transparency = transparency;

      if (rotation !== null) baseStyle.rotate = rotation;

      const hasFormatting = el.querySelector('b, i, u, strong, em, span, br');

      if (hasFormatting) {
        // Text with inline formatting
        const transformStr = computed.textTransform;
        const runs = parseInlineFormatting(el, {}, [], (str) => applyTextTransform(str, transformStr));

        // Adjust lineSpacing based on largest fontSize in runs
        const adjustedStyle = { ...baseStyle };
        if (adjustedStyle.lineSpacing) {
          const maxFontSize = Math.max(
            adjustedStyle.fontSize,
            ...runs.map(r => r.options?.fontSize || 0)
          );
          if (maxFontSize > adjustedStyle.fontSize) {
            const lineHeightMultiplier = adjustedStyle.lineSpacing / adjustedStyle.fontSize;
            adjustedStyle.lineSpacing = maxFontSize * lineHeightMultiplier;
          }
        }

        elements.push({
          type: el.tagName.toLowerCase(),
          text: runs,
          position: { x: pxToInch(x), y: pxToInch(y), w: pxToInch(w), h: pxToInch(h) },
          style: adjustedStyle
        });
      } else {
        // Plain text - inherit CSS formatting
        const textTransform = computed.textTransform;
        const transformedText = applyTextTransform(text, textTransform);

        const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;

        elements.push({
          type: el.tagName.toLowerCase(),
          text: transformedText,
          position: { x: pxToInch(x), y: pxToInch(y), w: pxToInch(w), h: pxToInch(h) },
          style: {
            ...baseStyle,
            bold: isBold && !shouldSkipBold(computed.fontFamily),
            italic: computed.fontStyle === 'italic',
            underline: computed.textDecoration.includes('underline')
          }
        });
      }

      processed.add(el);
    });

    return { background, elements, placeholders, errors };
  });
}

async function html2pptx(htmlFile, pres, options = {}) {
  const {
    tmpDir = process.env.TMPDIR || '/tmp',
    slide = null,
    preProcessSource = null,  // Tellr addition: optional JS string evaluated in-page before extraction
  } = options;

  try {
    // Use Chrome on macOS, default Chromium on Unix.
    // On Linux (Databricks Apps container), we run as non-root and need
    // --no-sandbox; --disable-dev-shm-usage avoids /dev/shm size issues
    // common in containers.
    // Merge with process.env so the chrome subprocess inherits LD_LIBRARY_PATH
    // (set by sidecar_subprocess_env() in pptx_from_html_huashu.py to point at
    // services/pptx-emit-huashu/sys-libs/ on Databricks Apps where the host
    // doesn't ship libnspr4/libnss3/etc.). Without the spread, Playwright would
    // pass only {TMPDIR} to chrome and the dynamic linker would fail.
    const launchOptions = { env: { ...process.env, TMPDIR: tmpDir } };
    if (process.platform === 'darwin') {
      launchOptions.channel = 'chrome';
    } else {
      launchOptions.args = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
      ];
    }

    const browser = await chromium.launch(launchOptions);

    let bodyDimensions;
    let slideData;

    const filePath = path.isAbsolute(htmlFile) ? htmlFile : path.join(process.cwd(), htmlFile);
    const validationErrors = [];

    try {
      const page = await browser.newPage();
      page.on('console', (msg) => {
        // Log the message text to your test runner's console
        console.log(`Browser console: ${msg.text()}`);
      });

      await page.goto(`file://${filePath}`);

      // Tellr addition: extra settle for slides that contain <canvas>
      // (Tellr Chart.js charts via CDN take up to ~3s to load + render
      // past the load event — chart-init IIFE has a setTimeout chain).
      // Without this wait, rasterizeCanvases sees a partially-drawn or
      // blank canvas, which exports as a smaller-than-native chart.
      // networkidle settles JS file fetches; then we wait for every
      // <canvas> to actually have non-empty drawing buffer.
      try {
        await page.waitForLoadState('networkidle', { timeout: 4000 });
      } catch (e) { /* ignore — some slides legitimately keep a long-poll open */ }
      // For slides with <canvas> (Tellr Chart.js charts), wait for the
      // canvas to have non-zero attributes (Chart.js sets these once it
      // initializes) AND for Chart.js's default animation (1s) to finish
      // before rasterizing. Without this, we either capture a blank
      // canvas (init not done) or a partial/mid-animation snapshot.
      // Slides without <canvas> skip this and proceed instantly.
      const canvasCount = await page.evaluate(() =>
        document.querySelectorAll('canvas').length
      );
      if (canvasCount > 0) {
        await page.waitForFunction(() => {
          const canvases = Array.from(document.querySelectorAll('canvas'));
          return canvases.every((c) => c.width > 0 && c.height > 0);
        }, { timeout: 5000 }).catch(() => {});
        // Chart.js default animation = 1000ms; wait 2000ms post-init to
        // be safe (covers the chart-init IIFE's own setTimeout chain
        // in Tellr's build_slide_html, plus the animation duration).
        await new Promise((r) => setTimeout(r, 2000));
      }

      // Tellr addition: run a DOM-mutation pass to bring the loaded slide
      // into compliance with huashu's 4 rules (wrap bare div text in <p>,
      // peel backgrounds off text tags, replace bg-image divs with <img>),
      // plus flatten tables and rasterize canvases so they survive the
      // export.
      if (preProcessSource) {
        try {
          const result = await page.evaluate(preProcessSource);
          if (result && typeof result === 'object') {
            console.log(`[preprocess] wrapped ${result.wrapped || 0} text nodes, ` +
                        `replaced ${result.replacedImgs || 0} bg-image divs, ` +
                        `peeled ${result.peeledTextTags || 0} text tags`);
          }
        } catch (e) {
          console.error(`[preprocess] failed: ${e.message} — continuing without`);
        }
      }

      bodyDimensions = await getBodyDimensions(page);

      await page.setViewportSize({
        width: Math.round(bodyDimensions.width),
        height: Math.round(bodyDimensions.height)
      });

      slideData = await extractSlideData(page);
    } finally {
      await browser.close();
    }

    // Collect all validation errors
    if (bodyDimensions.errors && bodyDimensions.errors.length > 0) {
      validationErrors.push(...bodyDimensions.errors);
    }

    const dimensionErrors = validateDimensions(bodyDimensions, pres);
    if (dimensionErrors.length > 0) {
      validationErrors.push(...dimensionErrors);
    }

    const textBoxPositionErrors = validateTextBoxPosition(slideData, bodyDimensions);
    if (textBoxPositionErrors.length > 0) {
      validationErrors.push(...textBoxPositionErrors);
    }

    if (slideData.errors && slideData.errors.length > 0) {
      validationErrors.push(...slideData.errors);
    }

    // Throw all errors at once if any exist — UNLESS bypassValidation is set
    // (Tellr: the Google Slides upload route passes bypassValidation=true so
    // every slide ends up in the deck even if it violates huashu's design
    // rules. Without bypass, failing slides get DROPPED from the output —
    // silent data loss. The modal huashu path keeps the strict throw to
    // surface design issues during local dev.)
    if (validationErrors.length > 0) {
      const errorMessage = validationErrors.length === 1
        ? validationErrors[0]
        : `Multiple validation errors found:\n${validationErrors.map((e, i) => `  ${i + 1}. ${e}`).join('\n')}`;
      if (options && options.bypassValidation) {
        console.warn('[html2pptx] validation errors bypassed (slide will still emit):\n' + errorMessage);
      } else {
        throw new Error(errorMessage);
      }
    }

    const targetSlide = slide || pres.addSlide();

    await addBackground(slideData, targetSlide, tmpDir);
    addElements(slideData, targetSlide, pres);

    return { slide: targetSlide, placeholders: slideData.placeholders };
  } catch (error) {
    if (!error.message.startsWith(htmlFile)) {
      throw new Error(`${htmlFile}: ${error.message}`);
    }
    throw error;
  }
}

module.exports = html2pptx;
