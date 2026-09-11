"""
Shared state object passed between all agents in the DataPilot graph.
Same "blackboard" pattern as job-intel-agent's state.py.
"""

from typing import TypedDict, Optional, List, Dict, Any, Literal


class AgentTrace(TypedDict):
    agent: str
    action: str
    detail: str


class GraphState(TypedDict, total=False):
    # ---- input ----
    raw_query: str
    dataset_name: str              # e.g. "sales" — table name in DuckDB

    # ---- planner output ----
    needs_sql: bool
    needs_python: bool             # for stats not expressible in plain SQL
    correlation_route: bool        # True only when the deterministic keyword override fired — this, not needs_python, drives actual routing
    needs_chart: bool              # deterministic keyword check (chart/graph/plot/visuali...) — drives the chart_agent branch
    plan: List[str]

    # ---- sql agent output ----
    schema_info: Optional[str]
    schema_columns: Optional[List[str]]   # plain column names, for the validator's column-match check
    sql_query: Optional[str]
    sql_result: Optional[List[Dict[str, Any]]]
    sql_error: Optional[str]
    sql_retry_count: int            # step 5: how many times SQL Agent has retried after a failure

    # ---- python agent output (step 6) ----
    python_code: Optional[str]
    python_result: Optional[Any]
    python_error: Optional[str]
    used_python: Optional[bool]     # which path (SQL vs Python) actually ran — the Validator branches on this

    # ---- validator output ----
    validated: Optional[bool]
    validation_notes: Optional[str]
    missing_columns: Optional[List[str]]   # columns the question mentioned that the SQL never used

    # ---- chart tool output (step 7) ----
    chart_spec: Optional[dict]
    chart_path: Optional[str]      # filesystem path to the generated PNG, if any
    chart_error: Optional[str]

    # ---- interpreter output ----
    final_answer: Optional[str]

    # ---- control / observability ----
    status: Literal["pending", "planning", "querying", "validating", "interpreting", "done", "rejected"]
    trace: List[AgentTrace]
    iteration_count: int
