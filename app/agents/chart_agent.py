"""
Chart Agent

Only reached when validated=True and needs_chart=True (see graph.py's
route_after_validation). Takes whatever rows the SQL or Python path
produced and, if the shape fits (>=2 rows, at least 2 fields — a
category and a value), generates a bar chart via the MCP chart_tool.

Doesn't fight for a chart on shapes that don't fit — a single-row
aggregate (e.g. "total revenue") has nothing to bar-chart, and that's
reported honestly rather than forced into a meaningless chart.
"""

from pathlib import Path

from app.state import GraphState
from app.mcp_client import call_mcp_tool

_CHART_SERVER = str(Path(__file__).parent.parent / "mcp_servers" / "chart_tool_server.py")


def _pick_axes(row: dict) -> tuple[str, str] | None:
    """Pick (category_field, value_field) by type, not by key order — SQL
    column order in the SELECT is not reliable evidence of which is the
    category and which is the value (see Q8: `SELECT SUM(sales) AS
    total_revenue, region FROM sales GROUP BY region` puts the numeric
    aggregate first, which the old keys[0]/keys[1] logic got backwards)."""
    numeric_keys, non_numeric_keys = [], []
    for k, v in row.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            numeric_keys.append(k)
        else:
            non_numeric_keys.append(k)
    if not numeric_keys or not non_numeric_keys:
        return None
    return non_numeric_keys[0], numeric_keys[0]


def chart_agent_node(state: GraphState) -> GraphState:
    trace = state.get("trace", [])
    rows = state.get("sql_result") or []

    if len(rows) < 2:
        error = f"Not enough rows to chart (need at least 2, got {len(rows)}) — the result is a single aggregate value, not a breakdown."
        trace.append({"agent": "chart_agent", "action": "generate_chart", "detail": error})
        return {**state, "chart_path": None, "chart_error": error, "trace": trace}

    axes = _pick_axes(rows[0])
    if axes is None:
        error = f"Couldn't find both a category and a numeric field to chart. Fields: {list(rows[0].keys())}"
        trace.append({"agent": "chart_agent", "action": "generate_chart", "detail": error})
        return {**state, "chart_path": None, "chart_error": error, "trace": trace}

    x_field, y_field = axes
    result = call_mcp_tool(
        _CHART_SERVER,
        "generate_bar_chart",
        {"data": rows, "x_field": x_field, "y_field": y_field, "title": state["raw_query"]},
    )

    trace.append({
        "agent": "chart_agent",
        "action": "generate_chart",
        "detail": f"x={x_field} y={y_field} error={result.get('error')} path={result.get('path')}",
    })

    return {
        **state,
        "chart_path": result.get("path"),
        "chart_error": result.get("error"),
        "trace": trace,
    }
