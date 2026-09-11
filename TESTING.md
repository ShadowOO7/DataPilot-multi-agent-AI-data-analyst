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

## Known limitations (see README for the full list)
Small-model self-correction isn't perfect (a genuinely malformed query
sometimes gets retried unchanged rather than fixed); no arbitrary Python
code execution by design; Python Agent's column list is hardcoded for
this fixed dataset; the Interpreter's narration of results isn't
fact-checked against the actual data (see the "13 unique orders" bug
above).
