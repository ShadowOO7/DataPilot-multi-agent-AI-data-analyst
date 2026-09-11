"""
MCP server: Python/pandas analysis tools, exposed over stdio.

DELIBERATE DESIGN CHOICE: this does NOT execute arbitrary LLM-generated
Python code (no `exec()`). The original project plan called for a
sandboxed `run_python(code, dataframe)` tool with Docker isolation — that
is real future work, but "never exec LLM-generated code without a
sandbox" is exactly the kind of shortcut that's easy to regret. Until
real sandboxing is in place, this server instead exposes a small, fixed
set of safe statistical operations. It solves the actual problem we hit
(Q6: correlation + raw values fighting DuckDB's GROUP BY rules) without
the exec() risk.
"""

from pathlib import Path

import pandas as pd
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("python-tool-server")

_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "sales.csv"

_NUMERIC_STATS = {"mean", "median", "std", "min", "max", "sum", "count"}


def _load_df() -> pd.DataFrame:
    return pd.read_csv(_DATA_PATH)


@mcp.tool()
def compute_correlation(column_x: str, column_y: str) -> dict:
    """Compute the Pearson correlation between two numeric columns.

    Args:
        column_x: first column name (must exist in the dataset and be numeric).
        column_y: second column name (must exist in the dataset and be numeric).
    """
    df = _load_df()
    for col in (column_x, column_y):
        if col not in df.columns:
            return {"error": f"[PYTHON_ERROR] Column '{col}' not found. Available: {list(df.columns)}", "result": None}
        if not pd.api.types.is_numeric_dtype(df[col]):
            return {"error": f"[PYTHON_ERROR] Column '{col}' is not numeric.", "result": None}

    corr = df[column_x].corr(df[column_y])
    return {
        "error": None,
        "result": {
            "column_x": column_x,
            "column_y": column_y,
            "correlation": round(float(corr), 4),
            "n": int(df[[column_x, column_y]].dropna().shape[0]),
        },
    }


@mcp.tool()
def compute_stat(column: str, stat: str) -> dict:
    """Compute a simple statistic (mean/median/std/min/max/sum/count) for a numeric column."""
    df = _load_df()
    if column not in df.columns:
        return {"error": f"[PYTHON_ERROR] Column '{column}' not found. Available: {list(df.columns)}", "result": None}
    if stat not in _NUMERIC_STATS:
        return {"error": f"[PYTHON_ERROR] Unsupported stat '{stat}'. Allowed: {sorted(_NUMERIC_STATS)}", "result": None}
    if not pd.api.types.is_numeric_dtype(df[column]) and stat != "count":
        return {"error": f"[PYTHON_ERROR] Column '{column}' is not numeric.", "result": None}

    value = getattr(df[column], stat)()
    return {"error": None, "result": {"column": column, "stat": stat, "value": round(float(value), 4)}}


if __name__ == "__main__":
    mcp.run(transport="stdio")
