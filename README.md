# DataPilot — AI Data Analyst Agent

Multi-agent system: ask a question about a dataset in plain language,
agents plan, generate SQL, execute it (read-only, via MCP), validate the
result, and explain it back in plain language — with guardrails, a Python
analysis path, charts, memory, and observability layered in as the build
progresses.

Builds on the same orchestration/MCP/guardrails skeleton as the
Job/Resume Intel Agent project — domain swapped, agent pattern reused.

## Status: Step 9 — Eval harness ✅

`tests/eval_harness.py` runs a benchmark of queries against the full
graph and checks results two ways:

1. **Ground truth checks** — numeric results (total revenue, grouped
   sums, correlation) are compared against values computed independently
   with pandas directly from the CSV, not against anything the agent
   itself produced. A must-fail case (the nonsense question) and a
   must-chart case are also checked.
2. **Row-count consistency** — a systematic version of the bug caught by
   hand in testing (Run 7, Q4: SQL correctly returned 20 rows, but the
   Interpreter's final answer said "13 unique orders"). This check scans
   every answer for stated counts ("13 orders", "4 regions", etc.) and
   flags it if none of them match the actual row count. Run on every
   case except the expected-failure one.

```bash
python -m tests.eval_harness
```

The Planner's own LLM-based `NEEDS_PYTHON` judgment proved unreliable
(flagged a nonsense shoe-size question as needing Python, missed both
real correlation questions). Fixed with a deterministic keyword override
in `planner.py`: any question mentioning "correlation" routes straight
to the new Python Agent instead of SQL — no more fighting DuckDB's
GROUP BY rules for something pandas does in one line.

`app/mcp_servers/python_tool_server.py` exposes `compute_correlation`
and `compute_stat` — **deliberately not arbitrary code execution**. The
original project plan called for a sandboxed `run_python(code, df)`
tool with Docker isolation; that's real future work, but exec()-ing
LLM-generated code without a sandbox in place is exactly the kind of
shortcut worth avoiding rather than "temporarily" allowing. This is a
small, fixed set of safe pandas operations instead — solves the actual
problem (Q6/Q3 correlation questions) without that risk.

Python Agent has no retry loop — a failure means the deterministic
column-lookup couldn't confidently map the question to two known
columns, and retrying the same lookup wouldn't help. The Validator
branches on a new `used_python` flag: Python-path results skip the
SQL-specific checks (column-match, NULL detection) since the tool
itself already validates its inputs.


## Architecture (full plan)

- **Planner** — decides if the question needs SQL, Python analysis, or both
- **SQL Agent** — fetches schema + generates + executes SQL, all via MCP
- **Python Agent** (step 6) — for stats SQL can't express (correlation, etc.)
- **Validator** — checks results are non-empty/error-free; will drive a
  retry loop back to SQL Agent (step 5)
- **Interpreter** — compiles plain-language answer, or explains failure
  honestly instead of hallucinating from bad data

**MCP layer**: `sql_tool` server now (get_schema, execute_sql). `python_tool`
and `chart_tool` servers added in steps 6-7, same MCP pattern.

**Guardrails**: SQL safety filter lives server-side in `sql_tool_server.py`
(read-only enforcement, blocked keywords, single-statement only) —
deliberately at the tool boundary, not trusted to the LLM's output alone.
Step 4 adds a broader guardrail layer (prompt-injection-aware, output
validation, loop/budget caps).

**Memory**: session state now; ChromaDB later for business-term RAG
(e.g. "revenue = gross sales - returns") — same idea as Job Intel Agent's
long-term memory step.

**Observability**: Langfuse tracing (step 8, shared plan with Job Intel Agent).

## Build order

1. ✅ Domain + sample dataset (`data/sales.csv`) + fixed test queries
2. ✅ State schema + baseline graph
3. ✅ MCP `sql_tool` server (DuckDB, read-only enforced)
4. ✅ Guardrail proven (`tests/test_sql_guardrail.py`, LLM-bypassing)
5. ✅ Self-correction retry loop (bad SQL → re-plan → re-execute)
6. ✅ Python analysis tool (MCP-wrapped) for non-SQL-expressible questions
7. ✅ Chart tool (MCP-wrapped) + visualization logic
8. ⬜ Memory (ChromaDB for business-term RAG) + observability (Langfuse)
9. ✅ Eval harness (this step)
10. ⬜ UI (Streamlit)

## Fixed test queries

1. Simple aggregation — total revenue
2. Group + filter — sales by region, Electronics only
3. Python-needed — correlation between discount and quantity (tests Planner
   routing `needs_python`, even though the Python tool doesn't exist yet)
4. Adversarial — SQL-injection-style instruction embedded in the question
   (tests the `sql_tool_server.py` read-only enforcement)
5. Nonsense / no-match — question the dataset can't answer (tests Validator
   catching a zero-row or malformed result honestly)

## Setup

**Two terminals — Ollama needs to stay running while the script runs.**

Terminal 1:
```bash
ollama serve
```

Terminal 2:
```bash
pip install -r requirements.txt
cp .env.example .env
ollama pull llama3.2:3b   # only needed once

python -m app.main
```

> Same `mcp<2.0.0` pin as Job Intel Agent — MCP 2.x renamed
> `FastMCP` to `MCPServer`. If you see
> `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, run
> `pip install "mcp<2.0.0" --force-reinstall`.

### How to tell if the SQL tool is working

- `sql_error` is `None` and `sql_result` has rows → real DuckDB execution worked
- `[BLOCKED_SQL]` in the trace → the read-only guardrail caught something
  (expected and correct for Q4, the adversarial query)
- `[MCP_CLIENT_ERROR]` → the MCP server process itself failed to start —
  check `duckdb` is installed

## Project structure

```
data/
  sales.csv              # sample dataset used by all test queries
app/
  state.py                # shared GraphState
  llm.py                  # centralized LLM client (Ollama default)
  mcp_client.py            # generalized MCP client (works with any server script)
  graph.py                 # LangGraph wiring
  main.py                  # entrypoint, runs 5 fixed test queries
  agents/
    planner.py
    sql_agent.py            # calls MCP sql_tool
    python_agent.py          # calls MCP python_tool (correlation questions)
    validator.py
    interpreter.py
  mcp_servers/
    sql_tool_server.py       # FastMCP server, DuckDB-backed, read-only enforced
    python_tool_server.py     # FastMCP server, pandas-backed, fixed safe stats only
    chart_tool_server.py       # FastMCP server, matplotlib-backed, fixed bar chart only
tests/
  test_sql_guardrail.py    # bypasses the LLM, proves the read-only guardrail directly
  eval_harness.py           # benchmark: ground-truth checks + row-count consistency check
```

Generated charts are written to `outputs/` (gitignored — regenerate by
running `python -m app.main`, don't expect them in the repo).

## Known limitations (honest, as of this commit)

- **Small-model self-correction is limited.** With `llama3.2:3b`, a
  genuinely malformed query (missing `FROM` clause) sometimes gets
  retried with the *identical* broken SQL rather than a fix — the retry
  cap still kicks in and the system fails honestly rather than
  hallucinating, but it doesn't always self-correct. A larger model
  would likely do better here; this is a model-capability limit, not a
  guardrail or architecture gap.
- **Column extraction for the Python Agent is a hardcoded candidate
  list** (`_CANDIDATE_COLUMNS` in `python_agent.py`), not fetched
  dynamically from the schema. Fine for this fixed dataset; would need
  generalizing for arbitrary uploaded datasets.
- **No arbitrary Python code execution.** By design (see step 6 above) —
  a real sandboxed `run_python(code, df)` tool is future work, not
  something this project currently does.
- **Routing between SQL and Python is keyword-based, not learned.** It's
  deliberately conservative (SQL is the default; only a correlation
  keyword match routes to Python) rather than trusting the small LLM's
  own judgment, after that judgment proved unreliable twice in testing
  (once flagging a nonsense question as Python-only with no SQL
  fallback). A broader set of "SQL can't express this well" cases
  (regression, forecasting) isn't covered yet.
- **The Interpreter's narration isn't fact-checked against the data.**
  Seen once in testing: a correct 20-row SQL result got summarized as
  "13 unique orders." The retry loop and guardrail both worked
  correctly — this is a separate LLM counting/narration error in the
  final answer step. Not currently caught by anything in the pipeline;
  a real fix belongs in an eval harness (step 9) that checks stated
  facts against the actual result data, not a one-off patch.
