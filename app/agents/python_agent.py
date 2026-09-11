"""
Python Agent

Alternative to SQL Agent for questions that fit pandas better than SQL —
right now: correlation between two columns (the exact Q6 failure mode:
"discount, quantity, and their correlation in one row" burned all 3 SQL
retries fighting DuckDB's GROUP BY rules; `df[x].corr(df[y])` solves it
in one call with no ambiguity).

Column extraction is deliberately simple (keyword matching against known
schema columns, not an LLM call) — reliable and fast for this narrow
tool, unlike the Planner's classification which we found unreliable for
deciding *whether* to route here in the first place (see planner.py's
keyword override).

No retry loop here: a failure means the tool couldn't confidently map
the question to two valid columns, and retrying the same deterministic
lookup would produce the same result — the Interpreter just explains it.
"""

from pathlib import Path

from app.state import GraphState
from app.mcp_client import call_mcp_tool
from app.utils import mentioned_columns

_PYTHON_SERVER = str(Path(__file__).parent.parent / "mcp_servers" / "python_tool_server.py")

# Known numeric columns worth correlating — kept explicit rather than
# fetched dynamically, since this agent only handles the correlation case.
_CANDIDATE_COLUMNS = ["sales", "quantity", "discount"]


def python_agent_node(state: GraphState) -> GraphState:
    trace = state.get("trace", [])
    question = state["raw_query"]

    cols = mentioned_columns(question, _CANDIDATE_COLUMNS)

    if len(cols) < 2:
        error = (
            f"Could not confidently identify two numeric columns to correlate "
            f"from the question (found: {cols}). Known correlatable columns: {_CANDIDATE_COLUMNS}."
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
