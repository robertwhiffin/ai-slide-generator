# Creating Custom Slide Styles

This guide covers what goes into a Slide Style, what CSS is safe to include, and how to convert an existing slide template into a style configuration.

## Defaults: corporate vs. personal

A new deck normally starts with a visual style applied — either a slide style or a [design system](./09-design-systems.md), and never both. It can start with neither: a profile you built that holds no style and no design system is used exactly as it stands, and so is a deck started in a workspace whose style library has no default style to fall back on. Which one you get depends on **how the deck was started**, so the cases below are separate rather than one ranking of settings.

**The deck in front of you.** Change the style from the agent config bar. That is an explicit choice, saved on this deck only, and no default overrides it afterwards.

**A brand-new deck in this browser.** The empty slot is filled once, stopping at the first that applies:

1. Your **personal design-system default** ("Set as default" on the Design Systems page).
2. Your **personal slide-style default** ("Set as default" on the Slide Styles page).
3. The organisation's **default design system**.
4. The organisation's **default slide style**.

**A personal slide-style default can stop the organisation's design system being applied.** Step 2 comes before step 3, so once your personal style claims the slot the org brand is not resolved for that deck at all. This is the opposite of what the ordering might suggest from the design-system side of the product. It applies only when the deck's starting point already carries a slide style, because the preference replaces a style rather than introducing one. The default profile that ships with tellr normally supplies one, but it is not guaranteed to — the exact condition is in [Design System Library §4](../technical/design-system-library.md).

**If this browser already holds a configuration you have used before, the choices you made yourself are kept** — a style or design system you picked is not replaced, including after an admin changes a corporate default. A slot the app filled in for you is different: if you never chose a design system yourself, a corporate design system set later can still take the slot on a subsequent load.

**A deck started from a profile.** A profile you built is treated as an explicit choice and nothing is layered over it. The default profile shipped with tellr is treated as a starting point, so the steps above may still fill its empty slots. A profile is also the only personal default that follows you between browsers and machines; both "Set as default" preferences are stored in this browser only.

**A deck created through the MCP API.** MCP cannot see anything in your browser. A style or design system passed explicitly in the call wins — and passing a slide style explicitly also stops the org design system being applied. Otherwise MCP uses the org default design system, then the organisation's default slide style.

**Where corporate defaults are set.** Tellr admins set the corporate slide style from the hidden `/admin` page ("Slide Style" tab) and the org design system from the same page's "Design System" tab. There is no link in the main navigation — you need the URL.

**If a configuration ends up carrying both, the design system wins.** A design system supplies the whole brand package — tokens, webfonts, brand imagery and named templates — so when both ids are present the design system is kept and the slide style is dropped. To use a slide style instead, set it explicitly on the deck from the agent config bar, or clear your personal design-system default on the Design Systems page.

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
| **Slide wrapper must carry `class="slide"`** | Discovery keys on the `slide` **class token**, not on the tag name, so `<div class="slide">` and `<section class="slide">` both work (design-system templates use the latter). What produces zero slides is an element **without** that class. |
| **Dimensions: 1280×720px** | The frontend iframe, presentation mode, and all export paths assume this fixed size. |
| **No presentation frameworks** | Do not instruct the AI to use reveal.js, Slidev, Impress.js, Marp, or any framework. These use incompatible DOM structures. |
| **CSS must be in `<style>` blocks** | The parser extracts CSS from `<style>` tags only. `<link>` references to external stylesheets are ignored. |
| **Shared CSS across all slides** | One `<style>` block covers the entire deck. Use specific class names (e.g., `.title-slide`, `.data-slide`) if you need per-slide differentiation. |

### Common Mistakes

| What the user writes | What breaks |
|---|---|
| "Use reveal.js for transitions" | Parser finds no element carrying the `slide` class — empty deck |
| "Use `<section>` tags for slides" | Fine **only if the class is there**: `<section class="slide">` is valid, a bare `<section>` is not |
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
   - Every slide root carries class="slide" — style this class as the slide
     container. <div class="slide"> and <section class="slide"> are both valid
   - Use descriptive class names for recurring elements
     (e.g., .title-slide, .content-slide, .metric-card, .section-header)
   - Include @import for any Google Fonts needed
   - Use CSS variables on :root for the color palette so colors are easy to adjust
   - Do NOT use any presentation framework markup (no reveal.js, Slidev, etc.)
   - Do NOT use <link> stylesheet references — all CSS must be in <style> blocks
   - Do NOT use framework-specific wrapper structures; the slide root must
     carry the "slide" class whatever its tag
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
