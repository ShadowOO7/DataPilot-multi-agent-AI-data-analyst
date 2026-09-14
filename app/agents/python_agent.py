"""
Python Agent

Alternative to SQL Agent for questions that fit pandas better than SQL —
right now: correlation between two columns (the exact Q6 failure mode:
"discount, quantity, and their correlation in one row" burned all 3 SQL
retries fighting DuckDB's GROUP BY rules; `df[x].corr(df[y])` solves it
in one call with no ambiguity).

Column extraction is deliberately simple (keyword matching against known
numeric schema columns, not an LLM call) — reliable and fast for this
narrow tool, unlike the Planner's classification which we found
unreliable for deciding *whether* to route here in the first place (see
planner.py's keyword override).

Candidate columns are fetched dynamically from the SQL tool's schema
(filtered to numeric types) rather than a hardcoded list — this used to
be `_CANDIDATE_COLUMNS = ["sales", "quantity", "discount"]`, which only
worked because it happened to match this exact dataset. Any CSV with
different numeric column names now works without editing this file.

No retry loop here: a failure means the tool couldn't confidently map
the question to two valid columns, and retrying the same deterministic
lookup would produce the same result — the Interpreter just explains it.
"""

from pathlib import Path

from app.state import GraphState
from app.mcp_client import call_mcp_tool
from app.utils import mentioned_columns

_PYTHON_SERVER = str(Path(__file__).parent.parent / "mcp_servers" / "python_tool_server.py")
_SQL_SERVER = str(Path(__file__).parent.parent / "mcp_servers" / "sql_tool_server.py")

# DuckDB numeric type names — matched as substrings against whatever
# get_schema reports (e.g. "DOUBLE", "BIGINT", "DECIMAL(10,2)").
_NUMERIC_TYPE_KEYWORDS = ["INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL", "HUGEINT"]


def _get_numeric_columns() -> list[str]:
    """Fetch the dataset's schema via the same MCP tool sql_agent uses,
    and return only the numeric column names. Never raises — an empty
    list here just means the agent will report 'couldn't identify
    columns' below, same as any other extraction failure."""
    try:
        schema = call_mcp_tool(_SQL_SERVER, "get_schema", {})
        if schema.get("error"):
            return []
        return [
            c["name"] for c in schema.get("columns", [])
            if any(kw in c["type"].upper() for kw in _NUMERIC_TYPE_KEYWORDS)
        ]
    except Exception:
        return []


def python_agent_node(state: GraphState) -> GraphState:
    trace = state.get("trace", [])
    question = state["raw_query"]

    candidate_columns = _get_numeric_columns()
    cols = mentioned_columns(question, candidate_columns)

    if len(cols) < 2:
        error = (
            f"Could not confidently identify two numeric columns to correlate "
            f"from the question (found: {cols}). Known numeric columns: {candidate_columns}."
        )
        trace.append({"agent": "python_agent", "action": "extract_columns", "detail": error})
        return {
            **state,
            "used_python": True,
            "sql_query": None,
            "sql_result": None,
            "sql_error": error,
            "trace": trace,
            "status": "validating",
        }

    col_x, col_y = cols[0], cols[1]
    result = call_mcp_tool(_PYTHON_SERVER, "compute_correlation", {"column_x": col_x, "column_y": col_y})

    trace.append({
        "agent": "python_agent",
        "action": "compute_correlation",
        "detail": f"columns=({col_x}, {col_y}) error={result.get('error')} result={result.get('result')}",
    })

    return {
        **state,
        "used_python": True,
        "sql_query": f"python: compute_correlation({col_x}, {col_y})",
        "sql_result": [result["result"]] if result.get("result") else None,
        "sql_error": result.get("error"),
        "trace": trace,
        "status": "validating",
    }
