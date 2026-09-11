"""
SQL Agent

1. Fetches schema via MCP `get_schema` tool.
2. Asks the LLM to write a SQL query for the question, given that schema.
3. Executes it via MCP `execute_sql` tool (which enforces read-only SQL
   server-side — see mcp_servers/sql_tool_server.py).

The agent never talks to DuckDB directly — only through MCP tool calls,
same principle as job-intel-agent's researcher -> web_search.
"""

from pathlib import Path

from app.state import GraphState
from app.llm import get_llm
from app.mcp_client import call_mcp_tool

_SQL_SERVER = str(Path(__file__).parent.parent / "mcp_servers" / "sql_tool_server.py")

SQL_GEN_PROMPT = """You write DuckDB SQL queries.

Table: {table}
Columns: {columns}

User question: {question}

Rules:
- If the question asks for a breakdown "by X" (e.g. "by region", "by product"),
  the query MUST include "GROUP BY X" and select X as a column, not just an
  aggregate total.
- Use ONLY the exact column names listed above that the question refers to.
  Do not substitute a different column even if it seems similar (e.g. if the
  question says "discount", do not write "sales" — check your query mentions
  the same column names the question mentions).
- If you select a mix of aggregate functions (SUM, AVG, CORR, etc.) and plain
  columns, every plain column MUST be in a GROUP BY clause, or don't select
  plain columns at all if you only want a single aggregate result.
- Write ONE read-only SQL query (SELECT/WITH only, no semicolons, no comments).

Respond with ONLY the SQL, nothing else — no markdown fences, no explanation.
"""

SQL_RETRY_PROMPT = """You write DuckDB SQL queries.

Table: {table}
Columns: {columns}

User question: {question}

Your previous attempt failed:
  SQL: {prev_sql}
  Error: {prev_error}

Fix the query so it runs successfully in DuckDB and still answers the
question. Apply the same rules as before (GROUP BY for breakdowns, exact
column names, no mixing aggregate + non-aggregate columns without
GROUP BY). Respond with ONLY the corrected SQL, nothing else.
"""


def sql_agent_node(state: GraphState) -> GraphState:
    trace = state.get("trace", [])

    schema = call_mcp_tool(_SQL_SERVER, "get_schema", {})
    if "error" in schema and schema.get("error"):
        trace.append({"agent": "sql_agent", "action": "get_schema", "detail": f"failed: {schema['error']}"})
        return {**state, "sql_error": schema["error"], "trace": trace, "status": "validating"}

    columns_str = ", ".join(f"{c['name']} ({c['type']})" for c in schema["columns"])
    column_names = [c["name"] for c in schema["columns"]]

    prev_error = state.get("sql_error")
    missing_cols = state.get("missing_columns")
    # A retry can be triggered either by a genuine execution error, or by
    # the Validator's column-match check (query ran fine but ignored a
    # column the question asked about — see Q3 in the third test run).
    retry_reason = prev_error or (
        f"The query executed successfully but never referenced these "
        f"column(s), which the question explicitly asks about: {missing_cols}. "
        f"Rewrite the query to use them." if missing_cols else None
    )
    retry_count = state.get("sql_retry_count", 0)

    if retry_reason:
        retry_count += 1
        trace.append({
            "agent": "sql_agent",
            "action": "retry",
            "detail": f"attempt {retry_count}, fixing: {retry_reason}",
        })
        prompt = SQL_RETRY_PROMPT.format(
            table=schema["table"],
            columns=columns_str,
            question=state["raw_query"],
            prev_sql=state.get("sql_query", ""),
            prev_error=retry_reason,
        )
    else:
        trace.append({"agent": "sql_agent", "action": "get_schema", "detail": f"{len(schema['columns'])} columns"})
        prompt = SQL_GEN_PROMPT.format(table=schema["table"], columns=columns_str, question=state["raw_query"])

    llm = get_llm()
    sql_query = llm.invoke(prompt).content.strip()
    # strip accidental markdown fences
    sql_query = sql_query.strip("`").replace("sql\n", "", 1) if sql_query.startswith("```") else sql_query
    sql_query = sql_query.strip()

    result = call_mcp_tool(_SQL_SERVER, "execute_sql", {"query": sql_query})

    trace.append({
        "agent": "sql_agent",
        "action": "execute_sql",
        "detail": f"query={sql_query!r} error={result.get('error')} rows={len(result.get('rows', []))}",
    })

    return {
        **state,
        "schema_info": columns_str,
        "schema_columns": column_names,
        "sql_query": sql_query,
        "sql_result": result.get("rows"),
        "sql_error": result.get("error"),
        "sql_retry_count": retry_count,
        "trace": trace,
        "status": "validating",
    }
