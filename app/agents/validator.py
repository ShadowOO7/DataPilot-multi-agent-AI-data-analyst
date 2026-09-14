"""
Validator Agent

Checks (in order): did the query error out? did it return zero rows?
did it return only NULLs? and now — did it actually use the columns the
question asked about? That last check is what catches the "SQL ran fine
but answered the wrong question" failure mode (Q3 in the test runs:
question asked about discount+quantity, generated SQL used sales+quantity
instead — no execution error, so the retry loop alone never caught it).

STEP 5 TODO (remaining): retry loop currently only feeds back a single
error/reason per attempt. If both a real error AND a column mismatch
happen across different retries, that's handled fine (each attempt gets
whatever's currently wrong) — but there's no cross-attempt memory beyond
the immediately previous one.
"""

import re
from app.state import GraphState
from app.utils import mentioned_columns


def _all_values_null(rows: list[dict]) -> bool:
    if not rows:
        return False
    for row in rows:
        for v in row.values():
            if v is not None:
                return False
    return True


def validator_node(state: GraphState) -> GraphState:
    trace = state.get("trace", [])

    sql_error = state.get("sql_error")
    sql_result = state.get("sql_result")
    sql_query = state.get("sql_query") or ""
    schema_columns = state.get("schema_columns") or []

    if state.get("used_python"):
        # Python Agent results are already structured/validated at the tool
        # level (see python_tool_server.py) — just check for a tool error.
        if state.get("sql_error"):
            trace.append({"agent": "validator", "action": "check_result", "detail": f"Python tool failed: {state['sql_error']}"})
            return {**state, "validated": False, "validation_notes": state["sql_error"], "missing_columns": None, "trace": trace, "status": "interpreting"}
        notes = f"OK — python tool returned {len(sql_result or [])} row(s)."
        trace.append({"agent": "validator", "action": "check_result", "detail": notes})
        return {**state, "validated": True, "validation_notes": notes, "missing_columns": None, "trace": trace, "status": "interpreting"}

    missing_columns = None

    if state.get("not_computable"):
        validated = False
        notes = sql_error or "This cannot be computed from the available data."
    elif sql_error:
        validated = False
        notes = f"SQL failed: {sql_error}"
    elif sql_result is None:
        validated = False
        notes = "No SQL result present (SQL step may have been skipped)."
    elif len(sql_result) == 0:
        validated = False
        notes = "Query executed but returned zero rows — question may not match the data."
    elif _all_values_null(sql_result):
        validated = False
        notes = "Query executed but every value returned was NULL — likely no matching data (e.g. a filter value that doesn't exist)."
    else:
        question_cols = mentioned_columns(state["raw_query"], schema_columns)
        sql_cols = mentioned_columns(sql_query, schema_columns)
        missing = [c for c in question_cols if c not in sql_cols]
        if missing:
            validated = False
            missing_columns = missing
            notes = f"SQL executed but ignored column(s) the question asked about: {missing}"
        else:
            validated = True
            notes = f"OK — {len(sql_result)} row(s) returned."

    trace.append({"agent": "validator", "action": "check_result", "detail": notes})

    return {
        **state,
        "validated": validated,
        "validation_notes": notes,
        "missing_columns": missing_columns,
        "trace": trace,
        "status": "interpreting",
    }
