"""
Planner Agent

Decides: does this question need SQL, Python (for stats SQL can't easily
express, e.g. correlation), or both.

The LLM's own NEEDS_PYTHON/NEEDS_SQL judgment turned out unreliable in
testing twice over: it missed real correlation questions, false-flagged
a nonsense one as needing Python, AND (see Q5 in the fourth test run) it
sometimes set needs_sql=False for an ordinary question with no keyword
signal at all — which would silently skip SQL for something SQL could
have answered fine, with no fallback.

Because of that, `correlation_route` (not `needs_python`) is what
actually drives graph routing (see graph.py's route_after_planning).
needs_sql/needs_python from the LLM are kept for the visible `plan` list
and trace only — informational, not control flow.
"""

from app.state import GraphState
from app.llm import get_llm
from app.memory import retrieve_business_context

PLANNER_PROMPT = """You are a planning agent for a data-analysis assistant.
The dataset is a sales table with columns like product, region, category,
sales, quantity, discount, order_date.

User question: {question}

Decide:
NEEDS_SQL: yes/no (almost always yes for questions about this data)
NEEDS_PYTHON: yes/no (yes only for things SQL can't do well: correlation,
  regression, forecasting, statistical tests)

Respond with exactly those two lines, nothing else.
"""

_CORRELATION_KEYWORDS = ["correlat", "relationship between"]
_CHART_KEYWORDS = ["chart", "graph", "plot", "visuali"]  # matches visualize/visualise


def planner_node(state: GraphState) -> GraphState:
    llm = get_llm()
    prompt = PLANNER_PROMPT.format(question=state["raw_query"])
    response = llm.invoke(prompt).content.lower()

    needs_sql = "needs_sql: yes" in response or "needs_sql:yes" in response
    needs_python = "needs_python: yes" in response or "needs_python:yes" in response

    question_lower = state["raw_query"].lower()
    correlation_route = any(kw in question_lower for kw in _CORRELATION_KEYWORDS)
    needs_chart = any(kw in question_lower for kw in _CHART_KEYWORDS)

    # Informational plan/trace only — actual routing uses correlation_route.
    if correlation_route:
        needs_python = True
        needs_sql = False
    else:
        # Never let the LLM's own judgment turn off SQL outside the one
        # deterministic case we trust — SQL is the safe default path.
        needs_sql = True

    plan = []
    if needs_sql:
        plan.append("query_sql")
    if needs_python:
        plan.append("python_analysis")
    plan.append("validate")
    if needs_chart:
        plan.append("generate_chart")
    plan.append("interpret")

    trace = state.get("trace", [])
    detail = f"plan={plan}"
    if correlation_route:
        detail += " (routed to Python by keyword match: correlation)"
    if needs_chart:
        detail += " (chart requested by keyword match)"
    trace.append({"agent": "planner", "action": "decide_plan", "detail": detail})

    business_context = retrieve_business_context(state["raw_query"])
    if business_context:
        trace.append({"agent": "planner", "action": "retrieve_memory", "detail": f"{len(business_context)} business-term note(s) retrieved"})

    return {
        **state,
        "needs_sql": needs_sql,
        "needs_python": needs_python,
        "correlation_route": correlation_route,
        "needs_chart": needs_chart,
        "business_context": business_context,
        "plan": plan,
        "status": "querying",
        "trace": trace,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }
