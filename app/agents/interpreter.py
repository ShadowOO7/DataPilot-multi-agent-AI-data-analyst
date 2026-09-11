"""
Interpreter Agent

Compiles the final answer. If the validator flagged a problem, explains
the failure honestly instead of hallucinating an answer from bad/no data —
this is a deliberate design choice, not just a fallback.
"""

from app.state import GraphState
from app.llm import get_llm

INTERPRET_PROMPT = """You are explaining a data query result to a business user.

Question: {question}
Method used: {sql}
Result rows (JSON): {rows}

Write a concise 2-4 sentence answer in plain language. Lead with the
direct answer, then one key insight if relevant. Do not mention SQL,
Python, or say "the query" — talk about the data itself.
"""

FAILURE_PROMPT = """A data query failed or returned nothing useful.

Question: {question}
Problem: {notes}

Write one short, honest sentence telling the user what went wrong and
suggest they rephrase or check the question, without technical jargon.
"""


def interpreter_node(state: GraphState) -> GraphState:
    llm = get_llm()
    trace = state.get("trace", [])

    if not state.get("validated"):
        prompt = FAILURE_PROMPT.format(
            question=state["raw_query"],
            notes=state.get("validation_notes", "unknown issue"),
        )
        answer = llm.invoke(prompt).content
        status = "rejected"
    else:
        prompt = INTERPRET_PROMPT.format(
            question=state["raw_query"],
            sql=state.get("sql_query", ""),
            rows=state.get("sql_result", [])[:20],  # cap rows sent to LLM
        )
        answer = llm.invoke(prompt).content
        status = "done"

        chart_path = state.get("chart_path")
        chart_error = state.get("chart_error")
        if chart_path:
            answer += f"\n\n[Chart saved to {chart_path}]"
        elif state.get("needs_chart") and chart_error:
            answer += f"\n\n(Couldn't generate a chart for this result: {chart_error})"

    trace.append({"agent": "interpreter", "action": "compile_answer", "detail": f"status={status}"})

    return {**state, "final_answer": answer, "status": status, "trace": trace}
