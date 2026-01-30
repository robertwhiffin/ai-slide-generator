"""HTML slide generators for creating test fixtures.

These generators create realistic HTML that mirrors what the LLM produces,
including proper Chart.js initialization with unique canvas IDs.
"""

from typing import List, Optional
import uuid


def _unique_id(prefix: str = "chart") -> str:
    """Generate a unique ID for canvas elements."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def generate_title_slide(
    title: str = "Quarterly Business Review",
    subtitle: str = "Q4 2024 Performance Analysis",
    author: str = "Data Team",
    date: str = "January 2025",
) -> str:
    """Generate a title slide HTML."""
    return f'''<div class="slide title-slide">
    <h1>{title}</h1>
    <div class="subtitle">{subtitle}</div>
    <div class="author">{author}</div>
    <div class="date">{date}</div>
</div>'''


def generate_section_slide(
    title: str = "Section Title",
    supporting_text: str = "Key Insights",
) -> str:
    """Generate a section divider slide HTML."""
    return f'''<div class="slide section-slide">
    <div class="supporting-text">{supporting_text}</div>
    <h2>{title}</h2>
</div>'''


def generate_content_slide(
    title: str = "Key Findings",
    subtitle: str = "Summary of analysis",
    bullet_points: Optional[List[str]] = None,
    slide_number: int = 1,
) -> str:
    """Generate a content slide with bullet points."""
    if bullet_points is None:
        bullet_points = [
            "First key insight from the data",
            "Second important observation",
            "Third actionable recommendation",
        ]

    bullets_html = "\n            ".join(f"<li>{point}</li>" for point in bullet_points)

    return f'''<div class="slide">
    <div class="slide-header">
        <h2>{title}</h2>
        <div class="subtitle">{subtitle}</div>
    </div>
    <div class="content">
        <ul>
            {bullets_html}
        </ul>
    </div>
    <div class="slide-number">{slide_number}</div>
</div>'''


def generate_two_column_slide(
    title: str = "Comparison Analysis",
    subtitle: str = "Side by side view",
    left_title: str = "Before",
    left_points: Optional[List[str]] = None,
    right_title: str = "After",
    right_points: Optional[List[str]] = None,
    slide_number: int = 1,
) -> str:
    """Generate a two-column slide."""
    if left_points is None:
        left_points = ["Previous state item 1", "Previous state item 2"]
    if right_points is None:
        right_points = ["New state item 1", "New state item 2", "Additional improvement"]

    left_bullets = "\n                ".join(f"<li>{p}</li>" for p in left_points)
    right_bullets = "\n                ".join(f"<li>{p}</li>" for p in right_points)

    return f'''<div class="slide">
    <div class="slide-header">
        <h2>{title}</h2>
        <div class="subtitle">{subtitle}</div>
    </div>
    <div class="two-column">
        <div class="column">
            <h3>{left_title}</h3>
            <ul>
                {left_bullets}
            </ul>
        </div>
        <div class="column">
            <h3>{right_title}</h3>
            <ul>
                {right_bullets}
            </ul>
        </div>
    </div>
    <div class="slide-number">{slide_number}</div>
</div>'''


def generate_chart_slide(
    title: str = "Revenue Trends",
    subtitle: str = "Quarterly performance",
    chart_type: str = "bar",
    canvas_id: Optional[str] = None,
    slide_number: int = 1,
    labels: Optional[List[str]] = None,
    data: Optional[List[int]] = None,
    colors: Optional[List[str]] = None,
) -> tuple[str, str]:
    """Generate a chart slide with Canvas element and Chart.js script.

    Returns:
        Tuple of (slide_html, script_js)
    """
    if canvas_id is None:
        canvas_id = _unique_id("chart")
    if labels is None:
        labels = ["Q1", "Q2", "Q3", "Q4"]
    if data is None:
        data = [150, 200, 180, 220]
    if colors is None:
        colors = ["#FF3621", "#3C71AF", "#4BA676", "#F2AE3D"]

    labels_str = str(labels)
    data_str = str(data)
    colors_str = str(colors)

    slide_html = f'''<div class="slide">
    <div class="slide-header">
        <h2>{title}</h2>
        <div class="subtitle">{subtitle}</div>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id}"></canvas>
    </div>
    <div class="slide-number">{slide_number}</div>
</div>'''

    script_js = f'''// Canvas: {canvas_id}
const ctx_{canvas_id} = document.getElementById('{canvas_id}');
if (ctx_{canvas_id}) {{
    new Chart(ctx_{canvas_id}.getContext('2d'), {{
        type: '{chart_type}',
        data: {{
            labels: {labels_str},
            datasets: [{{
                label: 'Value',
                data: {data_str},
                backgroundColor: {colors_str},
                borderWidth: 1
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{ display: false }}
            }}
        }}
    }});
}}'''

    return slide_html, script_js


def generate_table_slide(
    title: str = "Data Summary",
    subtitle: str = "Key metrics",
    headers: Optional[List[str]] = None,
    rows: Optional[List[List[str]]] = None,
    slide_number: int = 1,
) -> str:
    """Generate a slide with a data table."""
    if headers is None:
        headers = ["Metric", "Q3", "Q4", "Change"]
    if rows is None:
        rows = [
            ["Revenue", "$1.2M", "$1.5M", "+25%"],
            ["Users", "10,000", "15,000", "+50%"],
            ["Conversion", "3.2%", "4.1%", "+28%"],
        ]

    headers_html = "\n                ".join(f"<th>{h}</th>" for h in headers)
    rows_html = ""
    for row in rows:
        cells = "\n                    ".join(f"<td>{cell}</td>" for cell in row)
        rows_html += f'''            <tr>
                    {cells}
                </tr>
'''

    return f'''<div class="slide">
    <div class="slide-header">
        <h2>{title}</h2>
        <div class="subtitle">{subtitle}</div>
    </div>
    <div class="content">
        <table>
            <thead>
                <tr>
                    {headers_html}
                </tr>
            </thead>
            <tbody>
{rows_html}            </tbody>
        </table>
    </div>
    <div class="slide-number">{slide_number}</div>
</div>'''


def generate_deck_html(
    slide_count: int = 6,
    css: str = "",
    title: str = "Test Presentation",
    include_charts: bool = True,
) -> str:
    """Generate a complete slide deck HTML document.

    Args:
        slide_count: Number of slides to generate (3, 6, 9, or 12)
        css: Custom CSS to include (empty for default/inline styles)
        title: Document title
        include_charts: Whether to include chart slides

    Returns:
        Complete HTML document string
    """
    slides: List[str] = []
    scripts: List[str] = []
    slide_num = 1

    # Always start with title slide
    slides.append(generate_title_slide(title=title))
    slide_num += 1

    # Calculate how many of each type
    remaining = slide_count - 1  # Minus title slide

    # Distribution: section slides + content/chart mix
    if slide_count <= 3:
        # Small deck: title + 2 content/chart
        if include_charts:
            html, script = generate_chart_slide(
                title="Key Metrics",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1
            remaining -= 1

        slides.append(generate_content_slide(
            title="Summary",
            slide_number=slide_num,
        ))

    elif slide_count <= 6:
        # Medium deck: title + section + 4 content/chart
        slides.append(generate_section_slide(title="Performance Overview"))
        slide_num += 1

        if include_charts:
            html, script = generate_chart_slide(
                title="Revenue Trends",
                chart_type="bar",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

            html, script = generate_chart_slide(
                title="Growth Analysis",
                chart_type="line",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

        slides.append(generate_two_column_slide(slide_number=slide_num))
        slide_num += 1

        slides.append(generate_content_slide(
            title="Recommendations",
            slide_number=slide_num,
        ))

    elif slide_count <= 9:
        # Larger deck: title + 2 sections + 6 content/chart
        slides.append(generate_section_slide(title="Financial Overview"))
        slide_num += 1

        if include_charts:
            html, script = generate_chart_slide(
                title="Revenue by Quarter",
                chart_type="bar",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

        slides.append(generate_table_slide(slide_number=slide_num))
        slide_num += 1

        slides.append(generate_section_slide(title="Operational Metrics"))
        slide_num += 1

        if include_charts:
            html, script = generate_chart_slide(
                title="User Growth",
                chart_type="line",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

        slides.append(generate_two_column_slide(slide_number=slide_num))
        slide_num += 1

        slides.append(generate_content_slide(
            title="Key Takeaways",
            slide_number=slide_num,
        ))

    else:
        # Large deck: title + 3 sections + 8 content/chart
        slides.append(generate_section_slide(title="Executive Summary"))
        slide_num += 1

        slides.append(generate_content_slide(
            title="Overview",
            bullet_points=[
                "Strong Q4 performance across all regions",
                "Key initiatives delivered on schedule",
                "Customer satisfaction at all-time high",
            ],
            slide_number=slide_num,
        ))
        slide_num += 1

        slides.append(generate_section_slide(title="Financial Performance"))
        slide_num += 1

        if include_charts:
            html, script = generate_chart_slide(
                title="Revenue Breakdown",
                chart_type="bar",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

            html, script = generate_chart_slide(
                title="Profit Margins",
                chart_type="line",
                slide_number=slide_num,
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

        slides.append(generate_table_slide(slide_number=slide_num))
        slide_num += 1

        slides.append(generate_section_slide(title="Strategic Initiatives"))
        slide_num += 1

        if include_charts:
            html, script = generate_chart_slide(
                title="Initiative Progress",
                chart_type="bar",
                slide_number=slide_num,
                labels=["Initiative A", "Initiative B", "Initiative C"],
                data=[85, 70, 95],
            )
            slides.append(html)
            scripts.append(script)
            slide_num += 1

        slides.append(generate_two_column_slide(
            title="Next Steps",
            left_title="Short Term",
            right_title="Long Term",
            slide_number=slide_num,
        ))
        slide_num += 1

        slides.append(generate_content_slide(
            title="Conclusions",
            slide_number=slide_num,
        ))

    # Assemble the full HTML document
    slides_html = "\n\n".join(slides)
    scripts_html = "\n\n".join(scripts)

    # Default CSS if none provided
    if not css:
        css = '''
        .slide { width: 1280px; height: 720px; padding: 60px; background: #fff; margin-bottom: 20px; display: flex; flex-direction: column; }
        .slide h1, .slide h2 { margin: 0 0 20px 0; }
        .slide p { margin: 0 0 16px 0; line-height: 1.5; }
        .slide ul { margin: 0; padding-left: 24px; }
        .slide canvas { max-width: 100%; height: auto; }
        .title-slide { justify-content: center; align-items: center; text-align: center; background: #333; color: #fff; }
        .section-slide { justify-content: center; background: #FF3621; color: #fff; }
        .chart-container { flex: 1; display: flex; align-items: center; justify-content: center; }
        .two-column { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; flex: 1; }
        .slide-header { margin-bottom: 30px; }
        .slide-number { position: absolute; bottom: 20px; right: 40px; color: #888; }
        '''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
{css}
    </style>
</head>
<body>

{slides_html}

<script>
{scripts_html}
</script>

</body>
</html>'''

    return html
