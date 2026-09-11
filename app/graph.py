"""
Graph (steps 1-7): Planner -> [SQL Agent | Python Agent] -> Validator ->
[retry SQL Agent | Chart Agent | Interpreter].

Planner routes correlation questions straight to Python Agent (keyword
override — the LLM's own classification proved unreliable) and
everything else to SQL Agent. After a validated result, a chart is only
generated when the Planner's deterministic chart-keyword check fired —
Chart Agent then always proceeds to Interpreter regardless of whether
charting succeeded (a failed chart still gets an explained answer).

Retry loop (SQL path only): if the Validator finds a genuine SQL error
or a column-mismatch (not a zero-row/NULL result — those aren't fixable
by retrying), it routes back to SQL Agent with the problem description,
capped at MAX_SQL_RETRIES attempts.
"""

from langgraph.graph import StateGraph, START, END

from app.state import GraphState
from app.agents.planner import planner_node
from app.agents.sql_agent import sql_agent_node
from app.agents.python_agent import python_agent_node
from app.agents.validator import validator_node
from app.agents.chart_agent import chart_agent_node
from app.agents.interpreter import interpreter_node

MAX_SQL_RETRIES = 2


def route_after_planning(state: GraphState) -> str:
    return "python" if state.get("correlation_route") else "sql"


def route_after_validation(state: GraphState) -> str:
    if not state.get("used_python"):
        has_fixable_issue = bool(state.get("sql_error")) or bool(state.get("missing_columns"))
        retries_left = state.get("sql_retry_count", 0) < MAX_SQL_RETRIES
        if not state.get("validated") and has_fixable_issue and retries_left:
            return "retry"
    if state.get("validated") and state.get("needs_chart"):
        return "chart"
    return "interpret"


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("planner", planner_node)
    graph.add_node("sql_agent", sql_agent_node)
    graph.add_node("python_agent", python_agent_node)
    graph.add_node("validator", validator_node)
    graph.add_node("chart_agent", chart_agent_node)
    graph.add_node("interpreter", interpreter_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        route_after_planning,
        {"sql": "sql_agent", "python": "python_agent"},
    )
    graph.add_edge("sql_agent", "validator")
    graph.add_edge("python_agent", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validation,
        {"retry": "sql_agent", "chart": "chart_agent", "interpret": "interpreter"},
    )
    graph.add_edge("chart_agent", "interpreter")
    graph.add_edge("interpreter", END)

    return graph.compile()
