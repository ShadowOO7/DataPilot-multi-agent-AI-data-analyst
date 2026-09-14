# Testing Journal

This documents the actual iteration process against a real local model
(Ollama, `llama3.2:3b`) — kept deliberately as a record rather than
cleaned up, because the bugs found and how they were fixed are more
informative than a feature list claiming everything worked first try.

## Run 1 — MCP wiring broken
`pip install` resolved `mcp==2.2.0`, which renamed `FastMCP` to
`MCPServer` and broke the server import. Every tool call silently failed
and fell back to a mock. **Fix**: pinned `mcp<2.0.0` in `requirements.txt`.

## Run 2 — first real run against Ollama, 3 correctness bugs
1. A "total sales **by region**" question didn't get a `GROUP BY` —
   fixed with an explicit rule in the SQL generation prompt.
2. The LLM generated `CORR(sales, quantity)` for a question about
   `discount` and `quantity` — wrong columns, but the SQL executed
   successfully and the Interpreter confidently reported an answer
   anyway. No error-based check could ever catch this.
3. A query with no matching rows returned one row of `NULL`, and the
   Validator (checking only for zero rows) marked it valid. Fixed with
   an all-NULL check.

Also realized the LLM-driven adversarial test question (asking it to
`DROP TABLE`) proved nothing — the model just avoided the injection on
its own, so the guardrail itself was never actually exercised. Added
`tests/test_sql_guardrail.py`, which bypasses the LLM and sends known
malicious SQL straight to the MCP tool. **Result: 7/7 malicious queries
blocked, 3/3 safe queries pass** — this is the test that actually proves
the guardrail works, independent of model behavior.

## Run 3 — retry loop built, one gap found
Built the self-correction retry loop (SQL error → feed error back to
SQL Agent → retry, capped at 2 attempts). Confirmed working (a
GROUP-BY-fighting question correctly gave up after 2 failed retries with
an honest explanation). But bug #2 from Run 2 (wrong columns, no error)
came back — the error-based retry loop had nothing to catch, since
nothing errored.

## Run 4 — column-match check + Python Agent
Added a Validator check for whether the generated SQL actually
references the columns the question mentions, wired into the same retry
loop. Also noticed the Planner's own `NEEDS_PYTHON` classification was
unreliable — it missed two real correlation questions and false-flagged
an unrelated nonsense question. Built a Python Agent (MCP-wrapped,
`compute_correlation`/`compute_stat` — deliberately not arbitrary code
execution) and used a **deterministic keyword check**, not the LLM's
judgment, to route correlation questions there.

## Run 5 — a routing gap, not yet a visible bug
The correlation routing fix worked cleanly. But a non-correlation
question (bad "shoe size" test query) got `needs_sql=False` from the
Planner's LLM with **no keyword signal at all** — it happened to still
fail gracefully via the Python path, but nothing would have caught it if
that same misjudgment hit a question SQL could actually answer. Fixed by
introducing `correlation_route`, set only by the deterministic keyword
check, and making that (not `needs_python`) the actual routing signal.
SQL is now always the default path unless a correlation keyword fires.

## Run 6 — confirms the fixes
- Correlation questions: consistently correct, deterministic Python
  routing (`0.9427` every time, not a coin flip on columns).
- The "shoe size" question now correctly stays on the SQL path
  (`PLAN` includes `query_sql`, `USED_PYTHON: False`) and fails honestly
  via NULL-detection instead of skipping SQL.
- The retry loop **genuinely self-corrected** a real GROUP BY error in
  one retry — not just giving up, actually fixing itself.

## Run 7 — Chart tool built, one axis-assignment bug found
Q7 (grouped chart request) worked cleanly — correct bar chart, correct
data. But Q8 (meant to test the "single aggregate, can't chart"
graceful-failure path) exposed a different, more interesting bug: the
SQL Agent reasonably chose to group by region anyway
(`SELECT SUM(sales) AS total_revenue, region FROM sales GROUP BY
region`), and Chart Agent picked axes by **raw key order**
(`keys[0]` → x, `keys[1]` → y) rather than by data type. Since the
numeric aggregate was listed first in the SELECT, it got assigned to x
and the region string got assigned to y — backwards, and the chart
failed for the wrong reason. **Fixed**: axes are now picked by type (the
non-numeric field is always x/category, the numeric field is always
y/value), independent of column order in the SQL.

Also noticed, not yet fixed: on Q4 (the adversarial question, which
self-corrected successfully this run — see below), the Interpreter's
final answer claimed "13 unique orders" when the data actually had 20.
The retry loop and guardrail both worked correctly; this is a separate
LLM narration/counting hallucination in the Interpreter step, not caught
by anything currently in the pipeline. Documented as a known limitation
rather than fixed — a real fix would mean the Interpreter (or a new
fact-check step) verifying simple counts against the actual row data
before stating them, which is exactly the kind of thing an eval harness
(step 9) should catch systematically rather than one-off.

## Run 4 (same session) — retry loop genuinely self-corrected a real error
Worth noting explicitly: Q4 this run needed 2 retries to fix a real
GROUP BY violation, and succeeded on the third attempt with a valid,
correct query returning 20 rows — the clearest evidence yet that the
retry loop isn't just "give up gracefully," it actually works when the
model's mistake is fixable.

## Run 8 — chart axis fix confirmed, eval harness built
Re-ran after the axis-assignment fix: Q7 and Q8 both chart correctly now
(right category on x, right value on y, regardless of SELECT column
order). No regressions on Q1-Q6.

Built `tests/eval_harness.py` — a benchmark that checks numeric results
against ground truth computed independently with pandas (not anything
the agent produced), plus a **row-count consistency check** run on every
answer: does any count the Interpreter states in its final answer
("13 orders", "4 regions") actually match the real row count? This is
the systematic version of the Q4 hallucination caught by hand in Run 7
— now checked automatically on every eval run instead of only when
someone happens to notice it in a terminal log.

## Run 9 — eval harness: 9/9 passed
Ground truth checks (total revenue, grouped sums, correlation) all
matched pandas exactly — genuine verification, independent of anything
the agent itself produced. Honest caveat: `row_count_consistency` passed
on all 5 cases because none of their answers happened to state an
explicit count claim — the check is correctly wired and running, but
this particular benchmark set didn't actually exercise it against a real
violation. A case more likely to trigger a count claim (e.g. "how many
distinct products were sold?") would better prove it catches something,
not just that it doesn't false-positive.

## Run 10 — memory (ChromaDB) + observability built
Added `app/memory.py`: ChromaDB-backed retrieval of 5 business-term
definitions (revenue, profit, discount, region, order), injected into
the SQL Agent and Interpreter prompts via the Planner. New Q9 test case
("What is our profit margin?") exercises it — this dataset has no cost
data, so profit genuinely isn't computable, and the SQL Agent can now
respond `NOT_COMPUTABLE` instead of guessing at a query, with a
dedicated `not_computable` flag that blocks the retry loop from fighting
something that was never fixable in the first place.

Also added `app/observability.py`: local JSON trace logging (every run
dumped to `outputs/traces/`, always works) plus an optional Langfuse
hook wired centrally into `get_llm()` — activates only if credentials
are set in `.env`, otherwise a clean no-op. Not yet run against real
Langfuse credentials in this session (no account configured); the local
trace logging is the piece actually verified working.

## Run 11 — Q9 confirmed working, memory relevance threshold added
Full run confirmed step 8 working correctly: Q9 (profit margin) got
`SQL: None`, `VALIDATED: False`, no retry attempted (the `not_computable`
flag correctly blocked the retry loop), and an honest final answer
citing missing cost data. All Q1-Q8 stayed consistent, eval harness
still 9/9.

Noticed: every query retrieved exactly 2 business-term notes regardless
of relevance — e.g. the shoe-size nonsense question (Q5) pulled
"order_id" and "revenue" definitions that have nothing to do with it,
because retrieval had no similarity threshold, just top-k. Fixed by
filtering on ChromaDB's returned distances (`_MAX_DISTANCE` in
`memory.py`) so an unrelated question now returns no context instead of
the two least-irrelevant matches. The threshold value is an empirical
starting point, not tuned against this dataset's actual distance
distribution yet — `DEBUG_MEMORY=1` prints each query's candidates and
distances for that tuning.

## Run 12 — memory threshold confirmed well-calibrated, Python Agent generalized
`DEBUG_MEMORY=1` run confirmed `_MAX_DISTANCE = 1.0` works reasonably:
clearly relevant questions (Q1, Q7-Q9) retrieved notes at distance
0.74-0.87; clearly irrelevant ones (Q4, Q5) filtered out at 1.14-1.73.
Borderline case (Q3/Q6 correlation questions, where "discount" is
tangentially relevant at 1.07-1.42) got filtered — acceptable since
those questions are answered deterministically by the Python tool, not
an LLM prompt that would benefit from the context.

Also addressed a self-review point: Python Agent's column candidates
were a hardcoded list (`["sales", "quantity", "discount"]`) that only
worked because they happened to match this exact dataset. Now fetched
dynamically via the same `get_schema` MCP tool `sql_agent` already
uses, filtered to numeric DuckDB types — a CSV with different numeric
column names works without editing the file. (Two other self-review
points — narrow keyword-based routing, and Chart Agent/Validator
assumptions about this dataset's shape — are real and left as
documented limitations, not fixed: the routing one was a deliberate
reliability trade-off after the LLM's own judgment proved unreliable
twice in testing, not an oversight.)

## Run 13 — Streamlit UI added (step 10, final build-order item)
Added `streamlit_app.py` — a thin UI layer over the existing
`build_graph()`, no new agent logic. Chat-style interface, example
questions in the sidebar, charts rendered inline, an expandable panel
per answer showing SQL/Python used, business context, and the full
agent trace. Not yet run interactively in this session (no browser in
this environment) — syntax-checked and structurally verified against
the same state fields the CLI (`app/main.py`) already exercises, but
worth a manual click-through pass to confirm the actual browser
rendering (chat history ordering, chart image display, expander
contents) before treating it as fully proven the way the CLI path is.

## Known limitations (see README for the full list)
Small-model self-correction isn't perfect (a genuinely malformed query
sometimes gets retried unchanged rather than fixed); no arbitrary Python
code execution by design; the Interpreter's narration of results isn't
fact-checked against the actual data (see the "13 unique orders" bug
above); Langfuse integration is wired but not yet verified against a
real account; routing (SQL vs Python, chart-or-not) is keyword-based by
design, not a general classifier; Chart Agent and Validator still assume
this dataset's specific shape (single category + single value results).
