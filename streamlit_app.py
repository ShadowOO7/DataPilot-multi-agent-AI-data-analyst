"""
DataPilot — Streamlit UI (step 10)

Thin UI layer over the existing graph — no new agent logic here, just
wiring build_graph()'s output into a browser instead of a terminal.

Run: streamlit run streamlit_app.py
"""

import streamlit as st

from app.graph import build_graph
from app.observability import save_trace

st.set_page_config(page_title="DataPilot", page_icon="📊", layout="wide")

EXAMPLE_QUESTIONS = [
    "What is the total revenue across all sales?",
    "What is the total sales by region for the Electronics category?",
    "What is the correlation between discount and quantity sold?",
    "Show me a chart of total sales by region.",
    "What is our profit margin?",
]


@st.cache_resource
def get_graph():
    return build_graph()


def run_question(question: str) -> dict:
    graph = get_graph()
    state = graph.invoke({
        "raw_query": question,
        "dataset_name": "sales",
        "trace": [],
        "iteration_count": 0,
        "status": "pending",
    })
    save_trace(state, question[:40])
    return state


st.title("📊 DataPilot — AI Data Analyst")
st.caption(
    "Multi-agent orchestration (LangGraph) + MCP tools (SQL / Python / Chart) + "
    "guardrails, over a small sample sales dataset. Full build story in "
    "README.md and TESTING.md."
)

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.subheader("Try an example")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True):
            st.session_state.pending_question = q
    st.divider()
    st.caption(
        "This is a fixed-dataset demo (data/sales.csv), not a general "
        "'upload any CSV' tool — see README's Known Limitations for the "
        "honest scope of what this does and doesn't generalize to."
    )
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.history = []
        st.rerun()

question = st.chat_input("Ask a question about the sales data...")
if "pending_question" in st.session_state:
    question = st.session_state.pop("pending_question")

if question:
    with st.spinner("Thinking..."):
        try:
            result = run_question(question)
        except Exception as e:
            st.error(
                f"Something went wrong: {type(e).__name__}: {e}\n\n"
                "Check that Ollama is running (`ollama serve`) in another terminal."
            )
            result = None
    if result:
        st.session_state.history.append((question, result))

if not st.session_state.history:
    st.info("Ask a question, or pick an example from the sidebar, to get started.")

for past_question, result in reversed(st.session_state.history):
    with st.chat_message("user"):
        st.write(past_question)
    with st.chat_message("assistant"):
        answer = result.get("final_answer") or "(no answer produced)"
        # Strip the "[Chart saved to ...]" suffix used for terminal output —
        # the chart image renders directly below instead.
        answer = answer.split("\n\n[Chart saved to")[0]
        st.write(answer)

        chart_path = result.get("chart_path")
        if chart_path:
            st.image(chart_path)

        status = result.get("status")
        status_icon = {"done": "✅", "rejected": "⚠️"}.get(status, "❔")
        with st.expander(f"{status_icon} Details — status: {status}"):
            st.markdown(
                f"**Used Python tool:** `{result.get('used_python', False)}`  |  "
                f"**SQL retries:** `{result.get('sql_retry_count', 0)}`  |  "
                f"**Validated:** `{result.get('validated')}`"
            )
            if result.get("sql_query"):
                st.code(result["sql_query"], language="sql" if not result.get("used_python") else "text")
            if result.get("validation_notes"):
                st.caption(result["validation_notes"])
            if result.get("business_context"):
                st.markdown("**Business context used:**")
                for note in result["business_context"]:
                    st.markdown(f"- {note}")
            st.markdown("**Agent trace:**")
            st.json(result.get("trace", []))
