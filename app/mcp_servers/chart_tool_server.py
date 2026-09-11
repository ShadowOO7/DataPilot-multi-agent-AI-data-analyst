"""
MCP server: chart generation, exposed over stdio.

Same design choice as python_tool_server.py: one fixed, parameterized
chart function, not arbitrary LLM-generated plotting code. Bar charts
only for now — the data shapes this project currently produces (a
category + a value, from a GROUP BY) fit that; line/scatter would be
easy follow-ups if a question needs them.
"""

import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — no display server needed
import matplotlib.pyplot as plt

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chart-tool-server")

_OUTPUT_DIR = Path(__file__).parent.parent.parent / "outputs"


@mcp.tool()
def generate_bar_chart(data: list, x_field: str, y_field: str, title: str) -> dict:
    """Generate a bar chart PNG from a list of {x_field: ..., y_field: ...} rows.

    Args:
        data: list of row dicts (e.g. SQL/Python tool result rows).
        x_field: key to use for the category axis.
        y_field: key to use for the value axis (must be numeric).
        title: chart title.
    """
    if not data:
        return {"error": "[CHART_ERROR] No data provided.", "path": None}
    if x_field not in data[0] or y_field not in data[0]:
        return {"error": f"[CHART_ERROR] Fields not found in data. Have: {list(data[0].keys())}", "path": None}

    try:
        x_values = [str(row[x_field]) for row in data]
        y_values = [float(row[y_field]) for row in data]
    except (TypeError, ValueError) as e:
        return {"error": f"[CHART_ERROR] y_field values aren't numeric: {e}", "path": None}

    _OUTPUT_DIR.mkdir(exist_ok=True)
    filename = f"chart_{int(time.time() * 1000)}.png"
    path = _OUTPUT_DIR / filename

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x_values, y_values, color="#4C72B0")
    ax.set_xlabel(x_field)
    ax.set_ylabel(y_field)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

    return {"error": None, "path": str(path)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
