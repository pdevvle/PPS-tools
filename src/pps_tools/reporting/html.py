"""HTML report generation using Jinja2 templates."""

from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from pps_tools.storage.models import ComparisonRow
from pps_tools.analysis.trends import TrendSummary
from pps_tools.reporting.charts import generate_comparison_chart, generate_trend_chart, generate_heatmap

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def _embed_chart(chart_path: Path) -> str:
    """Convert a chart image to base64 for embedding in HTML."""
    with open(chart_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{data}"


def generate_comparison_report(
    rows: list[ComparisonRow],
    position_summary: dict,
    output_path: Path,
    title: str = "Competitor Price Comparison Report",
) -> Path:
    """Generate an HTML comparison report."""
    env = _get_env()
    template = env.get_template("report.html.j2")

    # Generate chart
    chart_path = output_path.parent / "comparison_chart.png"
    generate_comparison_chart(rows, chart_path, title)
    chart_data = _embed_chart(chart_path)

    # Generate heatmap
    heatmap_path = output_path.parent / "heatmap.png"
    generate_heatmap(rows, heatmap_path)
    heatmap_data = _embed_chart(heatmap_path)

    # Clean up temp chart files
    chart_path.unlink(missing_ok=True)
    heatmap_path.unlink(missing_ok=True)

    all_competitors = sorted(set(
        comp for row in rows for comp in row.competitor_prices.keys()
    ))

    html = template.render(
        title=title,
        rows=sorted(rows, key=lambda r: (r.product, r.quantity)),
        competitors=all_competitors,
        position_summary=position_summary,
        chart_image=chart_data,
        heatmap_image=heatmap_data,
    )

    output_path.write_text(html)
    return output_path


def generate_dashboard_report(
    comparison_rows: list[ComparisonRow],
    trend_summaries: list[TrendSummary],
    position_summary: dict,
    output_path: Path,
) -> Path:
    """Generate an HTML dashboard report."""
    env = _get_env()
    template = env.get_template("dashboard.html.j2")

    all_competitors = sorted(set(
        comp for row in comparison_rows for comp in row.competitor_prices.keys()
    ))

    # Generate charts
    charts = {}
    if comparison_rows:
        chart_path = output_path.parent / "dash_comparison.png"
        generate_comparison_chart(comparison_rows, chart_path, "Latest Prices")
        charts["comparison"] = _embed_chart(chart_path)
        chart_path.unlink(missing_ok=True)

    html = template.render(
        title="PPS Competitor Pricing Dashboard",
        comparison_rows=sorted(comparison_rows, key=lambda r: (r.product, r.quantity)),
        trend_summaries=trend_summaries,
        competitors=all_competitors,
        position_summary=position_summary,
        charts=charts,
    )

    output_path.write_text(html)
    return output_path
