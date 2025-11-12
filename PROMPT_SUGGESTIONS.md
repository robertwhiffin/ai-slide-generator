# Prompt Changes to Remove Navigation Buttons

## Issue
The LLM is generating slide decks with navigation buttons (Previous/Next) and JavaScript-based slide switching, but you want a scrollable single-page format instead.

## Root Causes

**1. Current CANVAS & LAYOUT Section** (lines 73-83 in `config/prompts.yaml`)
```yaml
CANVAS & LAYOUT (per slide):
- Slide size FIXED to 1280x720 (720p), white #FFFFFF background
- <body> styles: width:1280px; height:720px; margin:0; padding:0; overflow:hidden;
- Main container: max-width:1280px; max-height:720px; margin:0 auto;
```

The `overflow:hidden` and fixed `height:720px` on body prevents scrolling.

**2. HTML Output Requirements** (line 121)
```yaml
- Use reveal.js or similar slide framework structure if helpful
```

This encourages the LLM to add navigation frameworks.

## Recommended Changes

### Change 1: Replace CANVAS & LAYOUT Section

**Replace lines 73-83 with:**

```yaml
CANVAS & LAYOUT (scrollable format):

- Slide size: 1280px wide, 720px minimum height per slide, white #FFFFFF background
- <body> styles: width:1280px; margin:0 auto; padding:0; overflow-y:auto; overflow-x:hidden; background:#FFFFFF;
- Each slide container: width:1280px; min-height:720px; margin:0 auto; padding:48px 64px; page-break-after:always;
- Content area: padding:16px; box-sizing:border-box;
- Use flex layout: column; justify-between; gap ≥ 12px; min-height:0 on flex children
- All boxes/cards symmetrical; padding ≥16px; margin/gap ≥12px; border-radius 8–12px
- Shadow: 0 4px 6px rgba(0,0,0,.1); borders 1–2px #B2BAC0
- NO overflow or clipping. Wrap/ellipsize gracefully; never exceed viewport width
- Slides should stack vertically and be scrollable as a continuous webpage
- Each slide should maintain 1280px width and minimum 720px height but allow content to flow naturally
```

### Change 2: Update HTML Output Requirements

**Replace line 121 from:**
```yaml
- Use reveal.js or similar slide framework structure if helpful
```

**To:**
```yaml
- Create a scrollable single-page layout with vertically stacked slides
- DO NOT add navigation buttons or JavaScript slide switching
- All slides should be visible by scrolling down the page
```

### Change 3: Add Explicit Navigation Prohibition

**Add after line 128 (after CDNs section):**

```yaml

NAVIGATION & INTERACTION:

- DO NOT include Previous/Next navigation buttons
- DO NOT include JavaScript for slide switching or .active class toggling
- DO NOT use reveal.js, Swiper, or any slide navigation framework
- The output should be a single scrollable webpage with all slides visible
- Print-friendly: use page-break-after:always on each slide for proper printing
```

## Complete Updated Section

Here's the complete replacement for lines 73-129:

```yaml
CANVAS & LAYOUT (scrollable format):

- Slide size: 1280px wide, 720px minimum height per slide, white #FFFFFF background
- <body> styles: width:1280px; margin:0 auto; padding:0; overflow-y:auto; overflow-x:hidden; background:#FFFFFF;
- Each slide container: width:1280px; min-height:720px; margin:0 auto; padding:48px 64px; page-break-after:always;
- Content area: padding:16px; box-sizing:border-box;
- Use flex layout: column; justify-between; gap ≥ 12px; min-height:0 on flex children
- All boxes/cards symmetrical; padding ≥16px; margin/gap ≥12px; border-radius 8–12px
- Shadow: 0 4px 6px rgba(0,0,0,.1); borders 1–2px #B2BAC0
- NO overflow or clipping. Wrap/ellipsize gracefully; never exceed viewport width
- Slides should stack vertically and be scrollable as a continuous webpage
- Each slide should maintain 1280px width and minimum 720px height

TYPOGRAPHY (all slides):
- Modern geometric sans (Inter/SF Pro/Helvetica Now)
- H1 bold 40–52px; H2 28–36px; H3 24–28px; body 16–18px; captions 12–14px
- Title color: Navy 900 #102025 ONLY (not gray!)
- Subtitles: Navy 800 #2B3940
- Body text: #5D6D71
- Captions: #8D8E93

BRAND PALETTE (hex):
Primary: Lava 600 #EB4A34; Lava 500 #EB6C53; Navy 900 #102025; Navy 800 #2B3940
Neutrals: Oat Light #F9FAFB; Oat Medium #E4E5E5; Gray-Text #5D6D71; Gray-Muted #8D8E93; Gray-Lines #B2BAC0
Accents: Green 600 #4BA676; Yellow 600 #F2AE3D; Blue 600 #3C71AF; Maroon 600 #8C2330

COLOR USAGE RULES:
- Backgrounds: Oat Light (#F9FAFB) primary; Oat Medium (#E4E5E5) sparingly for bands/sidebars
- Emphasis/callouts/CTA buttons: Lava 600 (#EB4A34); hover/secondary: Lava 500 (#EB6C53)
- Status indicators: Success=Green, Warning=Yellow, Info=Blue, Critical=Lava/Maroon (max 1 per slide)
- Maintain high contrast; ensure all colors readable on white background

CHART GUIDELINES (when showing data):
- Chart types: bar/line/area/radar/scatter
- Use line charts for time series data.
- Use area charts for cumulative data.
- Use bar charts for categorical data.
- Use brand colors: ['#EB4A34','#4BA676','#3C71AF','#F2AE3D']
- Container with 12px outer margin; chart max-height 200px
- Set maintainAspectRatio:false for consistent sizing
- Enable labels, legend, and tooltips for clarity
- Ensure charts render well on high-DPI screens.


HTML output requirements:
- Generate complete, valid HTML5 with embedded CSS
- Use modern, professional styling with good typography
- Create a scrollable single-page layout with vertically stacked slides
- DO NOT add navigation buttons or JavaScript slide switching
- All slides should be visible by scrolling down the page
- Include proper semantic HTML tags
- Embed data visualizations using Chart.js

NAVIGATION & INTERACTION:
- DO NOT include Previous/Next navigation buttons
- DO NOT include JavaScript for slide switching or .active class toggling
- DO NOT use reveal.js, Swiper, or any slide navigation framework
- The output should be a single scrollable webpage with all slides visible
- Print-friendly: use page-break-after:always on each slide container for proper printing

CDNs (allowed on all slides):

- Tailwind: <script src="https://cdn.tailwindcss.com"></script>
- Chart.js: <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
- No other external JS libraries allowed.
```

## Expected Result

After these changes, the LLM will generate HTML like:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Presentation Title</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            width: 1280px;
            margin: 0 auto;
            padding: 0;
            overflow-y: auto;
            overflow-x: hidden;
            background: #FFFFFF;
        }
        
        .slide {
            width: 1280px;
            min-height: 720px;
            margin: 0 auto;
            padding: 48px 64px;
            page-break-after: always;
        }
    </style>
</head>
<body>
    <!-- Slide 1 -->
    <div class="slide">
        <h1>Title Slide</h1>
        <!-- content -->
    </div>
    
    <!-- Slide 2 -->
    <div class="slide">
        <h1>Content Slide</h1>
        <!-- content -->
    </div>
    
    <!-- No navigation buttons! -->
</body>
</html>
```

## Testing the Changes

1. Update `config/prompts.yaml` with the changes above
2. Run: `python test_multi_turn_live.py --auto`
3. Check the output HTML - it should:
   - ✅ Have no navigation buttons
   - ✅ Be scrollable vertically
   - ✅ Show all slides stacked
   - ✅ Have no `.active` class or slide switching JavaScript

## Migration Note

If you have existing sessions/conversations, they may still reference the old prompt structure. For best results:
- Clear any active sessions
- Restart the agent
- Start a fresh conversation to use the updated prompt

