"""Mock LLM edit response fixtures.

These simulate what the LLM returns when asked to edit slides.
Each function returns HTML that the slide replacement logic must process.
"""

from typing import Optional
import uuid


def _unique_id(prefix: str = "chart") -> str:
    """Generate a unique ID for canvas elements."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def get_recolor_chart_response(
    canvas_id: str,
    new_colors: Optional[list] = None,
    chart_type: str = "bar",
) -> str:
    """Simulate LLM response for recoloring a chart.

    This is a common edit operation. The response should:
    - Preserve the canvas ID exactly
    - Only change color values
    - Include both the slide HTML and the script

    Args:
        canvas_id: The original canvas ID to preserve
        new_colors: New color palette to use
        chart_type: Type of chart

    Returns:
        HTML fragment with slide and script
    """
    if new_colors is None:
        # Switch to a blue/green palette
        new_colors = ["#2563EB", "#3B82F6", "#60A5FA", "#93C5FD"]

    colors_str = str(new_colors)

    return f'''<style>
.chart-container {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f9f9f9;
    border-radius: 12px;
    padding: 20px;
}}
</style>

<div class="slide">
    <div class="slide-header">
        <h2>Revenue Trends</h2>
        <div class="subtitle">Updated color scheme</div>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id}"></canvas>
    </div>
</div>

<script data-slide-scripts>
// Canvas: {canvas_id}
const ctx = document.getElementById('{canvas_id}');
if (ctx) {{
    new Chart(ctx.getContext('2d'), {{
        type: '{chart_type}',
        data: {{
            labels: ['Q1', 'Q2', 'Q3', 'Q4'],
            datasets: [{{
                label: 'Revenue',
                data: [150, 200, 180, 220],
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
}}
</script>'''


def get_reword_content_response(
    new_title: str = "Updated Key Findings",
    new_subtitle: str = "Revised analysis summary",
    new_bullet_points: Optional[list] = None,
) -> str:
    """Simulate LLM response for rewording slide content.

    This tests text-only edits without chart changes.

    Args:
        new_title: New slide title
        new_subtitle: New subtitle
        new_bullet_points: New bullet points

    Returns:
        HTML fragment with updated slide
    """
    if new_bullet_points is None:
        new_bullet_points = [
            "Revised insight based on new data analysis",
            "Updated recommendation with additional context",
            "New action item for the team to consider",
            "Additional point added for completeness",
        ]

    bullets_html = "\n            ".join(f"<li>{point}</li>" for point in new_bullet_points)

    return f'''<div class="slide">
    <div class="slide-header">
        <h2>{new_title}</h2>
        <div class="subtitle">{new_subtitle}</div>
    </div>
    <div class="content">
        <ul>
            {bullets_html}
        </ul>
    </div>
</div>'''


def get_add_slide_response(
    canvas_id: Optional[str] = None,
    include_chart: bool = True,
) -> str:
    """Simulate LLM response for adding a new slide.

    This tests the "add" operation where new content is inserted.

    Args:
        canvas_id: Canvas ID for new chart (generated if not provided)
        include_chart: Whether to include a chart

    Returns:
        HTML fragment with new slide(s)
    """
    if canvas_id is None:
        canvas_id = _unique_id("newChart")

    if include_chart:
        return f'''<style>
.new-slide-style {{
    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
}}
</style>

<div class="slide new-slide-style">
    <div class="slide-header">
        <h2>Additional Analysis</h2>
        <div class="subtitle">New insights discovered</div>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id}"></canvas>
    </div>
</div>

<script data-slide-scripts>
// Canvas: {canvas_id}
const newCtx = document.getElementById('{canvas_id}');
if (newCtx) {{
    new Chart(newCtx.getContext('2d'), {{
        type: 'doughnut',
        data: {{
            labels: ['Category A', 'Category B', 'Category C'],
            datasets: [{{
                data: [45, 30, 25],
                backgroundColor: ['#FF6384', '#36A2EB', '#FFCE56']
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false
        }}
    }});
}}
</script>'''
    else:
        return '''<div class="slide">
    <div class="slide-header">
        <h2>Additional Context</h2>
        <div class="subtitle">Supporting information</div>
    </div>
    <div class="content">
        <p>This slide provides additional context for the analysis.</p>
        <ul>
            <li>First supporting point</li>
            <li>Second supporting point</li>
            <li>Third supporting point</li>
        </ul>
    </div>
</div>'''


def get_consolidate_slides_response() -> str:
    """Simulate LLM response for consolidating multiple slides into one.

    This tests the case where 3 slides become 1 (net change: -2).

    Returns:
        HTML fragment with consolidated slide
    """
    return '''<style>
.consolidated-view {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 24px;
    flex: 1;
}

.summary-card {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 20px;
    border-left: 4px solid #FF3621;
}

.summary-card h4 {
    font-size: 18px;
    margin: 0 0 12px 0;
    color: #333;
}

.summary-card ul {
    margin: 0;
    padding-left: 20px;
    font-size: 14px;
}

.summary-card li {
    margin-bottom: 6px;
}
</style>

<div class="slide">
    <div class="slide-header">
        <h2>Strategic Summary</h2>
        <div class="subtitle">Consolidated recommendations</div>
    </div>
    <div class="consolidated-view">
        <div class="summary-card">
            <h4>Short Term</h4>
            <ul>
                <li>Immediate action item 1</li>
                <li>Immediate action item 2</li>
            </ul>
        </div>
        <div class="summary-card">
            <h4>Medium Term</h4>
            <ul>
                <li>Q2 initiative</li>
                <li>Q3 milestone</li>
            </ul>
        </div>
        <div class="summary-card">
            <h4>Long Term</h4>
            <ul>
                <li>Annual goal</li>
                <li>Multi-year vision</li>
            </ul>
        </div>
    </div>
</div>'''


def get_expand_slide_response(
    canvas_id_1: Optional[str] = None,
    canvas_id_2: Optional[str] = None,
) -> str:
    """Simulate LLM response for expanding 1 slide into 2.

    This tests the case where 1 slide becomes 2 (net change: +1).

    Args:
        canvas_id_1: Canvas ID for first chart
        canvas_id_2: Canvas ID for second chart

    Returns:
        HTML fragment with expanded slides
    """
    if canvas_id_1 is None:
        canvas_id_1 = _unique_id("expandChart1")
    if canvas_id_2 is None:
        canvas_id_2 = _unique_id("expandChart2")

    return f'''<style>
.expanded-slide {{
    background: #fafafa;
}}
</style>

<div class="slide expanded-slide">
    <div class="slide-header">
        <h2>Detailed Analysis - Part 1</h2>
        <div class="subtitle">Regional breakdown</div>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id_1}"></canvas>
    </div>
</div>

<div class="slide expanded-slide">
    <div class="slide-header">
        <h2>Detailed Analysis - Part 2</h2>
        <div class="subtitle">Time series view</div>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id_2}"></canvas>
    </div>
</div>

<script data-slide-scripts>
// Canvas: {canvas_id_1}
const ctx1 = document.getElementById('{canvas_id_1}');
if (ctx1) {{
    new Chart(ctx1.getContext('2d'), {{
        type: 'bar',
        data: {{
            labels: ['APAC', 'EMEA', 'Americas'],
            datasets: [{{
                label: 'Revenue',
                data: [120, 95, 150],
                backgroundColor: ['#4BC0C0', '#FF6384', '#36A2EB']
            }}]
        }},
        options: {{ responsive: true, maintainAspectRatio: false }}
    }});
}}

// Canvas: {canvas_id_2}
const ctx2 = document.getElementById('{canvas_id_2}');
if (ctx2) {{
    new Chart(ctx2.getContext('2d'), {{
        type: 'line',
        data: {{
            labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
            datasets: [{{
                label: 'Trend',
                data: [65, 72, 78, 85, 92, 98],
                borderColor: '#FF3621',
                fill: false
            }}]
        }},
        options: {{ responsive: true, maintainAspectRatio: false }}
    }});
}}
</script>'''


def get_malformed_response_duplicate_canvas() -> str:
    """Generate a malformed response with duplicate canvas IDs.

    This is used to test that validation catches corruption.
    """
    canvas_id = "duplicatedChart"

    return f'''<div class="slide">
    <div class="slide-header">
        <h2>Chart 1</h2>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id}"></canvas>
    </div>
</div>

<div class="slide">
    <div class="slide-header">
        <h2>Chart 2 (DUPLICATE ID - CORRUPTED)</h2>
    </div>
    <div class="chart-container">
        <canvas id="{canvas_id}"></canvas>
    </div>
</div>

<script>
const ctx = document.getElementById('{canvas_id}');
if (ctx) {{
    new Chart(ctx.getContext('2d'), {{ type: 'bar', data: {{ labels: [], datasets: [] }} }});
}}
</script>'''


def get_malformed_response_syntax_error() -> str:
    """Generate a malformed response with JavaScript syntax error.

    This is used to test that validation catches corruption.
    """
    return '''<div class="slide">
    <div class="slide-header">
        <h2>Chart with Broken Script</h2>
    </div>
    <div class="chart-container">
        <canvas id="brokenChart"></canvas>
    </div>
</div>

<script>
// This script has syntax errors
const ctx = document.getElementById('brokenChart');
if (ctx) {
    new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
            labels: ['A', 'B', 'C'],
            datasets: [{
                data: [1, 2, 3]
            }]
        // Missing closing braces - syntax error
</script>'''
