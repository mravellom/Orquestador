"""Portfolio report generation with HTML template."""
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape
import os

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def render_html_report(report_data: dict) -> str:
    """Render portfolio report as HTML."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("portfolio.html")
    return template.render(
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        **report_data,
    )
