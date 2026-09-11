"""
MCP server: exposes `get_schema` and `execute_sql` tools over stdio,
backed by an in-memory DuckDB instance loaded from data/sales.csv.

SAFETY: execute_sql only allows read-only statements. This check lives
here (server-side, at the tool boundary) rather than trusting the agent
to only ever generate safe SQL — the LLM's SQL is untrusted input.
A stronger prompt-injection-aware guardrail (checking the *question*,
not just the generated SQL) is added in step 4.
"""

import re
from pathlib import Path

import duckdb
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sql-tool-server")

_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "sales.csv"
_TABLE_NAME = "sales"

_BLOCKED_KEYWORDS = [
    "drop", "delete", "update", "insert", "alter", "create",
    "truncate", "attach", "copy", "pragma", "install", "load",
    "grant", "revoke", "call", "export", "import",
]


def _get_connection():
    con = duckdb.connect(database=":memory:")
    con.execute(f"CREATE TABLE {_TABLE_NAME} AS SELECT * FROM read_csv_auto('{_DATA_PATH}')")
    return con


def _is_read_only(sql: str) -> tuple[bool, str]:
    """Very deliberately conservative: allow only SELECT/WITH statements,
    single statement only (no semicolon-chaining), and reject any blocked
    keyword anywhere in the string (catches subqueries/CTEs too)."""
    stripped = sql.strip().rstrip(";").strip()
    lowered = stripped.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False, "Only SELECT/WITH statements are allowed."

    if ";" in stripped:
        return False, "Multiple statements are not allowed."

    for kw in _BLOCKED_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            return False, f"Blocked keyword detected: {kw}"

    return True, ""


@mcp.tool()
def get_schema() -> dict:
    """Return the table name and column names/types for the loaded dataset."""
    con = _get_connection()
    try:
        rows = con.execute(f"DESCRIBE {_TABLE_NAME}").fetchall()
        columns = [{"name": r[0], "type": r[1]} for r in rows]
        return {"table": _TABLE_NAME, "columns": columns}
    finally:
        con.close()


@mcp.tool()
def execute_sql(query: str) -> dict:
    """Execute a read-only SQL query against the 'sales' table and return rows.

    Args:
        query: a single SELECT/WITH statement. DROP/DELETE/UPDATE/INSERT/
               ALTER/CREATE and other mutating or multi-statement SQL are
               rejected before execution.
    """
    ok, reason = _is_read_only(query)
    if not ok:
        return {"error": f"[BLOCKED_SQL] {reason}", "rows": []}

    con = _get_connection()
    try:
        result = con.execute(query)
        cols = [d[0] for d in result.description]
        rows = [dict(zip(cols, row)) for row in result.fetchall()]
        return {"error": None, "rows": rows}
    except Exception as e:
        return {"error": f"[SQL_ERROR] {type(e).__name__}: {e}", "rows": []}
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
