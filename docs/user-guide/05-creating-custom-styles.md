# Creating Custom Slide Styles

This guide covers what goes into a Slide Style, what CSS is safe to include, and how to convert an existing slide template into a style configuration.

## Overview

A Slide Style is a text block that tells the AI how your slides should look. It can contain:

- **Natural language** describing typography, colors, layout, and content density
- **Raw CSS** that the AI will include verbatim in the generated `<style>` block
- **A mix of both** — natural language sections alongside a CSS stylesheet

The AI reads the entire style and produces HTML + CSS that follows it. Understanding what the rendering pipeline supports (and what breaks it) lets you write styles that work reliably.

## Prerequisites

- Access to Databricks Tellr
- Familiarity with [creating and selecting styles](./03-advanced-configuration.md#part-2-slide-styles) in the UI
- Basic CSS knowledge (for pasting raw CSS)

---

## What You Can Include

### Natural Language Guidance

Describe the visual appearance in plain text. The AI interprets this and generates matching CSS.

```
Typography & Colors:
- Headings: 'Roboto', sans-serif | Body: 'Open Sans', sans-serif
- H1: 44px bold, #1A1A2E | H2: 30px semibold, #16213E | Body: 16px, #4A4A68
- Primary accent: #E94560 | Secondary: #0F3460

Layout & Structure:
- Content padding: 48px horizontal, 40px vertical
- Cards: padding 24px, border-radius 12px, subtle shadow
- Use flexbox with 16px gaps for multi-column layouts

Content Per Slide:
- ONE clear title (≤55 chars) stating the key insight
- Body text ≤40 words
- Maximum 2 data visualizations per slide
```

### Raw CSS

You can paste a complete stylesheet. The AI will include it in the `<style>` block of the generated HTML.

```css
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap');

:root {
  --color-primary: #E94560;
  --color-heading: #1A1A2E;
  --color-body: #4A4A68;
  --font-heading: 'Roboto', sans-serif;
}

body {
  width: 1280px;
  height: 720px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  font-family: var(--font-heading);
}

.slide {
  width: 1280px;
  height: 720px;
  padding: 40px 48px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

h1 { color: var(--color-heading); font-size: 44px; font-weight: 700; }
h2 { color: var(--color-heading); font-size: 30px; font-weight: 600; }
```

### Chart Brand Colors

Provide an array of hex codes. The AI uses these for Chart.js dataset colors.

```
Chart Brand Colors:
['#E94560','#0F3460','#2ECC71','#F39C12','#8E44AD']
```

### CSS Features That Work

| Feature | Example |
|---------|---------|
| CSS variables | `:root { --primary: #EB4A34; }` |
| Google Fonts | `@import url('https://fonts.googleapis.com/...')` |
| `@font-face` | Custom font definitions |
| Flexbox / Grid | Any layout mode |
| Gradients, shadows, transforms | Standard CSS visual properties |
| Animations / transitions | `@keyframes`, `transition` |
| Class selectors | `.metric-card`, `.title-slide`, `.section-header` |
| Tailwind utility classes | Mention in natural language; the CDN is optionally loaded |

---

## Fixed Constraints

The rendering pipeline has structural requirements that **cannot be overridden** by a style. If a style causes the AI to violate these, slides will fail to parse or render incorrectly.

| Constraint | Detail |
|---|---|
| **Slide wrapper must be `<div class="slide">`** | The parser uses `find_all('div', class_='slide')` at every stage — parsing, editing, validation. A `<section>`, `<article>`, or any other element produces zero slides. |
| **Dimensions: 1280×720px** | The frontend iframe, presentation mode, and all export paths assume this fixed size. |
| **No presentation frameworks** | Do not instruct the AI to use reveal.js, Slidev, Impress.js, Marp, or any framework. These use incompatible DOM structures. |
| **CSS must be in `<style>` blocks** | The parser extracts CSS from `<style>` tags only. `<link>` references to external stylesheets are ignored. |
| **Shared CSS across all slides** | One `<style>` block covers the entire deck. Use specific class names (e.g., `.title-slide`, `.data-slide`) if you need per-slide differentiation. |

### Common Mistakes

| What the user writes | What breaks |
|---|---|
| "Use reveal.js for transitions" | Parser finds zero `<div class="slide">` elements — empty deck |
| "Use `<section>` tags for slides" | Same — `<section class="slide">` does not match the parser |
| "Set slides to 1920×1080" | Slides overflow the 1280×720 iframe; charts mis-scale |
| "Link to an external stylesheet" | `<link>` tags are ignored; styles don't apply |
| `.slide { display: none; }` | Slides parse correctly but render as invisible |

---

## Converting an Existing Template

If you have an existing slide template (PowerPoint, Google Slides, or a PDF export), you can convert it into a Tellr Slide Style using any LLM. Export a few representative slides as a PDF or take screenshots, then use the prompt below.

### Step 1: Export Your Template

Export 3–5 representative slides from your template as a PDF or screenshots. Include at least:
- A title slide
- A content slide with text
- A data/chart slide (if applicable)

### Step 2: Use the Conversion Prompt

Copy the prompt below and paste it into an LLM (Claude, ChatGPT, etc.) along with your PDF or screenshots. The code block has a **copy button** in the top-right corner.

```text title="Template Conversion Prompt — copy and paste into an LLM"
I'm attaching a PDF/screenshot of a slide template I want to replicate.
Analyze it and produce a Slide Style configuration I can paste into my
slide generator app.

Output format — return a single text block containing:

1. A SLIDE VISUAL STYLE: header
2. A "Typography & Colors" section listing:
   - Font families for headings and body (use Google Fonts or common system fonts)
   - Exact sizes in px for H1, H2, H3, body text, captions
   - Hex color codes for all text levels, backgrounds, and accents
3. A "Layout & Structure" section listing:
   - Padding, margins, and gaps (in px)
   - Card/box styling: border-radius, shadows, border colors
   - Flexbox or grid layout preferences
   - Any recurring layout patterns (e.g., two-column, sidebar, full-bleed header)
4. A "Chart Brand Colors" array of hex codes for data visualizations,
   extracted from the template palette
5. A "CSS" section containing a complete stylesheet that implements the
   above. The CSS must follow these rules:
   - Target a fixed slide canvas of 1280x720px
   - Include: body { width: 1280px; height: 720px; margin: 0; padding: 0; overflow: hidden; }
   - Every slide is wrapped in <div class="slide"> — style this class as the slide container
   - Use descriptive class names for recurring elements
     (e.g., .title-slide, .content-slide, .metric-card, .section-header)
   - Include @import for any Google Fonts needed
   - Use CSS variables on :root for the color palette so colors are easy to adjust
   - Do NOT use any presentation framework markup (no reveal.js, Slidev, etc.)
   - Do NOT use <link> stylesheet references — all CSS must be in <style> blocks
   - Do NOT use <section> or <article> as slide wrappers — only <div class="slide">
6. A "Content Per Slide" section with guidelines like max words, max charts,
   title length

Below is an example of the expected output structure. Your output should
follow this format but reflect the actual template I attached.

--- EXAMPLE OUTPUT ---

SLIDE VISUAL STYLE:

Typography & Colors:
- Headings: 'Roboto', sans-serif | Body: 'Open Sans', sans-serif
- H1: 44px bold, #1A1A2E | H2: 30px semibold, #16213E | Body: 16px, #4A4A68
- Primary accent: #E94560 | Secondary: #0F3460 | Success: #2ECC71
- Background: #FFFFFF | Card background: #F8F9FA

Layout & Structure:
- Fixed slide size: 1280x720px, white background
- Body: width:1280px; height:720px; margin:0; padding:0; overflow:hidden
- Content padding: 48px horizontal, 40px vertical
- Cards: padding 24px, border-radius 12px, shadow 0 2px 8px rgba(0,0,0,0.08)
- Use flexbox with gap: 16px for multi-column layouts

Chart Brand Colors:
['#E94560','#0F3460','#2ECC71','#F39C12','#8E44AD']

CSS:
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&family=Open+Sans:wght@400;600&display=swap');

:root {
  --color-primary: #E94560;
  --color-secondary: #0F3460;
  --color-heading: #1A1A2E;
  --color-body: #4A4A68;
  --color-bg: #FFFFFF;
  --color-card-bg: #F8F9FA;
  --font-heading: 'Roboto', sans-serif;
  --font-body: 'Open Sans', sans-serif;
}

body {
  width: 1280px;
  height: 720px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  font-family: var(--font-body);
  background: var(--color-bg);
}

.slide {
  width: 1280px;
  height: 720px;
  padding: 40px 48px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

h1 {
  font-family: var(--font-heading);
  color: var(--color-heading);
  font-size: 44px;
  font-weight: 700;
  margin: 0 0 8px 0;
}

h2 {
  font-family: var(--font-heading);
  color: var(--color-heading);
  font-size: 30px;
  font-weight: 600;
  margin: 0 0 16px 0;
}

.metric-card {
  background: var(--color-card-bg);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.title-slide {
  justify-content: center;
  align-items: center;
  text-align: center;
  background: linear-gradient(135deg, var(--color-primary), var(--color-secondary));
  color: #FFFFFF;
}

.title-slide h1 { color: #FFFFFF; font-size: 52px; }

Content Per Slide:
- ONE clear title (<=55 chars) stating the key insight
- Subtitle for context
- Body text <=40 words
- Maximum 2 data visualizations per slide

--- END EXAMPLE ---

Now analyze the attached template and produce the complete Slide Style.
```

### Step 3: Paste Into Tellr

1. Copy the entire output from the LLM
2. In Tellr, go to **Slide Styles** → **+ Create Style**
3. Paste the output into the **Style Content** field
4. Give it a name and category, then save
5. Assign the style to a profile and generate a test deck to verify

---

## Tips

- **Start from the default** — Duplicate the system "Default" style and modify it rather than starting from scratch
- **Use CSS variables** — `:root` variables make it easy to tweak the palette without editing every rule
- **Name your classes** — Descriptive class names like `.kpi-card` or `.section-divider` give the AI clear hooks to use
- **Test iteratively** — Generate a quick 3-slide deck after each style change to see the effect
- **Keep content guidance** — Include natural language rules like "max 40 words per slide" alongside your CSS; the AI follows both

## Related Guides

- [Advanced Configuration](./03-advanced-configuration.md) — Create and manage styles in the UI
- [Creating Profiles](./02-creating-profiles.md) — Assign a style to a profile
- [Generating Slides](./01-generating-slides.md) — See your style in action
