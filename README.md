# DataPilot — AI Data Analyst Agent

Multi-agent system: ask a question about a dataset in plain language.
Agents plan, generate/execute SQL (or route to a Python tool when SQL
genuinely doesn't fit), validate the result, optionally chart it, and
explain it back honestly — including saying "I can't compute that"
instead of guessing. Built with LangGraph orchestration, real MCP tool
servers, guardrails proven independent of LLM behavior, a self-correction
retry loop, ChromaDB memory, and an eval harness with ground-truth checks.

Builds on the same orchestration/MCP/guardrails skeleton as the
Job/Resume Intel Agent project — domain swapped, agent pattern reused.

**All 10 steps of the build are complete.** See `TESTING.md` for the
full run-by-run debugging journal (12 real test runs, every bug found
and how it was fixed) — that document is arguably more informative than
this one about how the system actually behaves.

## Architecture

```
                         ┌─────────────┐
                         │   Planner   │  keyword routing (correlation → Python,
                         │             │  chart request → Chart Agent) + memory
                         └──────┬──────┘  retrieval (ChromaDB business terms)
                                │
                  ┌─────────────┴─────────────┐
                  ▼                            ▼
          ┌───────────────┐            ┌───────────────┐
          │   SQL Agent    │            │  Python Agent  │
          │ (MCP sql_tool) │            │(MCP python_tool)│
          └───────┬───────┘            └───────┬───────┘
                  │                            │
                  └─────────────┬──────────────┘
                                 ▼
                          ┌─────────────┐
                          │  Validator  │──── retry (SQL path only,
                          │             │      capped, on genuine errors
                          └──────┬──────┘      or column mismatches)
                                 │
                       validated?│
                    ┌────────────┴────────────┐
                    ▼                          ▼
            ┌───────────────┐          ┌─────────────┐
            │  Chart Agent   │          │ Interpreter │
            │(MCP chart_tool)│─────────▶│             │
            └───────────────┘          └─────────────┘
```

- **Planner** — decides SQL vs Python (deterministic keyword check, not
  LLM judgment — see Known Limitations for why), whether a chart was
  asked for, and retrieves relevant business-term context from memory.
- **SQL Agent** — fetches schema + generates + executes SQL, entirely
  through MCP tool calls. Can respond `NOT_COMPUTABLE` when business
  context says a question isn't answerable from this data (e.g. profit).
- **Python Agent** — handles correlation questions SQL fights with
  (aggregate + raw columns "in one row"). No arbitrary code execution —
  fixed, safe pandas operations only.
- **Validator** — catches SQL errors, zero-row/NULL-only results, and
  column-mismatches (SQL that runs fine but ignores a column the
  question asked about). Drives the retry loop.
- **Chart Agent** — generates a bar chart when asked, picking axes by
  data type (not SQL column order — a real bug found and fixed in
  testing). Fails gracefully on shapes that don't fit.
- **Interpreter** — compiles the final plain-language answer, or
  explains a failure honestly instead of hallucinating from bad data.

**MCP layer**: `sql_tool`, `python_tool`, `chart_tool` — three real MCP
servers over stdio, not hardcoded functions. Agents talk to them the
same way they'd talk to any MCP-compliant tool.

**Guardrails**: read-only SQL enforcement lives server-side in
`sql_tool_server.py` (blocks DROP/DELETE/UPDATE/INSERT/ALTER, rejects
multi-statement SQL) — and is proven to work independent of the LLM's
behavior via `tests/test_sql_guardrail.py` (7/7 malicious queries
blocked, 3/3 safe queries pass), not just by an adversarial test
question that the model might happen to dodge on its own.

**Memory**: `app/memory.py` — ChromaDB-backed retrieval of 5 business-term
definitions (revenue, profit, discount, region, order), filtered by a
distance threshold so irrelevant questions get no injected context.
Concrete payoff: this dataset has no cost data, so the SQL Agent can
correctly decline profit questions instead of guessing.

**Observability**: `app/observability.py` — every run's full state is
logged to `outputs/traces/*.json` (always works, no external account).
Langfuse is wired too, centrally in `get_llm()`, but only activates if
credentials are set in `.env` — never required to run the project.

**Eval harness**: `tests/eval_harness.py` checks numeric results against
ground truth computed independently with pandas (not the agent's own
output), plus a row-count consistency check that scans the Interpreter's
answers for stated counts and flags mismatches against the real data.

## Build order

1. ✅ Domain + sample dataset (`data/sales.csv`) + fixed test queries
2. ✅ State schema + baseline graph
3. ✅ MCP `sql_tool` server (DuckDB, read-only enforced)
4. ✅ Guardrail proven (`tests/test_sql_guardrail.py`, LLM-bypassing)
5. ✅ Self-correction retry loop (bad SQL → re-plan → re-execute)
6. ✅ Python analysis tool (MCP-wrapped) for non-SQL-expressible questions
7. ✅ Chart tool (MCP-wrapped) + visualization logic
8. ✅ Memory (ChromaDB for business-term RAG) + observability (Langfuse)
9. ✅ Eval harness
10. ✅ UI (Streamlit)

## Setup

**Two terminals — Ollama needs to stay running while anything else runs.**

Terminal 1 (leave running):
```bash
ollama serve
```

Terminal 2:
```bash
pip install -r requirements.txt
cp .env.example .env
ollama pull llama3.2:3b   # only needed once
```

> Pinned to `mcp<2.0.0` — MCP 2.x renamed `FastMCP` to `MCPServer` and
> broke this project's server code. If you see
> `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, run
> `pip install "mcp<2.0.0" --force-reinstall`.

## Running it

**CLI** — runs the fixed test queries and prints full trace/debug info:
```bash
python -m app.main
```

**UI** — chat-style interface, example questions in the sidebar, charts
rendered inline, an expandable panel per answer showing the SQL/Python
used, business context, and full agent trace:
```bash
streamlit run streamlit_app.py
```

**Guardrail proof** — bypasses the LLM entirely, sends known-malicious
SQL straight to the MCP tool:
```bash
python -m tests.test_sql_guardrail
```

**Eval harness** — ground-truth + row-count consistency checks:
```bash
python -m tests.eval_harness
```

Set `DEBUG_MEMORY=1` before any of the above to print ChromaDB's actual
retrieval distances per question (useful for tuning `_MAX_DISTANCE` in
`app/memory.py`).

## Fixed test queries

1. Simple aggregation — total revenue
2. Group + filter — sales by region, Electronics only
3. Correlation — discount vs quantity (routes to Python Agent)
4. Adversarial — SQL-injection-style instruction embedded in the question
5. Nonsense / no-match — question the dataset can't answer
6. SQL-error-prone — tests the retry loop directly
7. Chart request — grouped data, should produce a real bar chart
8. Chart on a shape that may or may not reduce to a single aggregate
9. Business-term memory — profit margin (not computable from this data)

## Project structure

```
data/
  sales.csv                 # sample dataset used by all test queries
app/
  state.py                   # shared GraphState
  llm.py                     # centralized LLM client (Ollama default) + Langfuse wiring point
  mcp_client.py               # generalized MCP client (works with any server script)
  memory.py                   # ChromaDB business-term retrieval
  observability.py             # local trace logging + optional Langfuse handler
  utils.py                    # shared helpers (e.g. mentioned_columns)
  graph.py                    # LangGraph wiring
  main.py                     # CLI entrypoint, runs fixed test queries
  agents/
    planner.py                  # routing + memory retrieval
    sql_agent.py                # calls MCP sql_tool
    python_agent.py              # calls MCP python_tool (correlation questions)
    validator.py
    chart_agent.py               # calls MCP chart_tool
    interpreter.py
  mcp_servers/
    sql_tool_server.py           # FastMCP server, DuckDB-backed, read-only enforced
    python_tool_server.py         # FastMCP server, pandas-backed, fixed safe stats only
    chart_tool_server.py           # FastMCP server, matplotlib-backed, fixed bar chart only
tests/
  test_sql_guardrail.py       # bypasses the LLM, proves the read-only guardrail directly
  eval_harness.py               # benchmark: ground-truth checks + row-count consistency check
streamlit_app.py               # UI entrypoint
```

Generated charts are written to `outputs/` and run traces to
`outputs/traces/` (both gitignored — regenerate by running the app).
ChromaDB's local data lives in `chroma_data/` (also gitignored,
regenerated automatically on first run).

## Known limitations (honest)

- **Small-model self-correction is limited.** With `llama3.2:3b`, a
  genuinely malformed query sometimes gets retried with the *identical*
  broken SQL rather than a fix — the retry cap still kicks in and the
  system fails honestly rather than hallucinating, but it doesn't always
  self-correct. A larger model would likely do better; this is a
  model-capability limit, not a guardrail or architecture gap.
- **No arbitrary Python code execution.** By design — a real sandboxed
  `run_python(code, df)` tool with Docker isolation is future work.
  exec()-ing LLM-generated code without a sandbox in place was
  deliberately avoided rather than "temporarily" allowed.
- **Routing between SQL and Python is keyword-based, not learned.**
  Deliberately conservative (SQL is the default; only a correlation
  keyword match routes to Python) after the LLM's own routing judgment
  proved unreliable twice in testing — once nearly skipping SQL entirely
  with no fallback. A broader set of "SQL can't express this well" cases
  (regression, forecasting) isn't covered.
- **Chart Agent and Validator assume this dataset's specific shape.**
  Chart Agent only produces one shape (category + numeric value → bar
  chart); the Validator's checks are written against this table's
  structure. Generalizing to arbitrary uploaded datasets would need both
  to reason about shape/schema dynamically.
- **Python Agent's column discovery is dynamic (fixed from an earlier
  hardcoded list)** — fetched from the SQL tool's schema at runtime,
  filtered to numeric types, so a different dataset's numeric columns
  work without editing the file.
- **The Interpreter's narration isn't fully fact-checked against the
  data.** Seen once in testing: a correct 20-row SQL result got
  summarized as "13 unique orders." Partly addressed by
  `tests/eval_harness.py`'s row-count consistency check, which hasn't
  yet caught a live violation on this benchmark — only proven to not
  false-positive.
- **Business-term memory covers 5 fixed, hand-written terms.** Adding
  new ones means editing `_SEED_TERMS` in `app/memory.py` directly.
  Retrieval distance threshold (`_MAX_DISTANCE`) is an empirical
  starting point, confirmed reasonable via `DEBUG_MEMORY=1` runs but not
  rigorously tuned.
- **Langfuse integration is wired but not verified** against real
  credentials — only local trace logging has been confirmed working.
- **This is a single-dataset prototype, not a general data-analyst
  tool.** It demonstrates the architecture pattern — multi-agent
  orchestration, MCP tool boundaries, guardrails proven independent of
  LLM behavior, retry/self-correction, memory, eval — on one fixed CSV.
  Supporting arbitrary uploaded datasets (the original project plan's
  Phase 5) would need the points above addressed, not just more test
  questions against this one.

## Setup notes for the UI specifically

The Streamlit app is a thin layer over the same `build_graph()` used by
the CLI — no separate agent logic. Each question still spawns fresh MCP
subprocess calls per tool use (same as the CLI), so expect the same
per-query latency you'd see running `python -m app.main`, just rendered
in a browser instead of a terminal.
