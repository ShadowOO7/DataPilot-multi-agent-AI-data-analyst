"""
Eval harness: runs a benchmark of queries against the full graph and
checks results against independently-computed ground truth — computed
directly from the CSV with pandas, not from anything the agent produced,
so this can't just agree with its own mistakes.

Two kinds of checks:
1. Per-case numeric/behavioral checks (does the SQL/Python result match
   the real sum/group-by/correlation? did it fail when it should?).
2. A universal "row-count consistency" check run on every successful
   case: does the Interpreter's stated count of rows/orders/records
   actually match the real row count? This is the systematic version of
   the bug caught by hand in testing (Q4: SQL correctly returned 20
   rows, Interpreter's final answer said "13 unique orders").

Run: python -m tests.eval_harness
"""

import re
from pathlib import Path

import pandas as pd

from app.graph import build_graph

_DATA_PATH = Path(__file__).parent.parent / "data" / "sales.csv"
_TOLERANCE = 0.02  # relative tolerance for float comparisons


def _ground_truth_df() -> pd.DataFrame:
    return pd.read_csv(_DATA_PATH)


def _close(actual: float, expected: float, tol: float = _TOLERANCE) -> bool:
    if expected == 0:
        return abs(actual) < 0.01
    return abs(actual - expected) / abs(expected) <= tol


def _first_numeric_value(row: dict):
    for v in row.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return None


def check_row_count_consistency(answer: str, actual_row_count: int) -> tuple[bool, str]:
    """Does any stated count in the answer (e.g. '13 unique orders') match
    the real row count? Flags exactly the class of bug found in Run 7's
    Q4 test (stated 13, actual 20)."""
    pattern = r"\b(\d+)\s+(?:unique\s+|distinct\s+)?(?:orders?|rows?|records?|entries|transactions?|items?|regions?|products?|customers?)\b"
    matches = re.findall(pattern, answer.lower())
    if not matches:
        return True, "no row-count claim detected in answer"
    stated = [int(m) for m in matches]
    if actual_row_count in stated:
        return True, f"stated count(s) {stated} include the actual row count ({actual_row_count})"
    return False, f"stated count(s) {stated} do NOT match actual row count ({actual_row_count})"


def check_total_revenue(state: dict, df: pd.DataFrame) -> tuple[bool, str]:
    expected = round(float(df["sales"].sum()), 2)
    rows = state.get("sql_result") or []
    if len(rows) != 1:
        return False, f"expected 1 row, got {len(rows)}"
    actual = _first_numeric_value(rows[0])
    if actual is None or not _close(actual, expected):
        return False, f"expected ~{expected}, got {actual}"
    return True, f"matches ground truth ({expected})"


def check_electronics_by_region(state: dict, df: pd.DataFrame) -> tuple[bool, str]:
    expected = df[df["category"] == "Electronics"].groupby("region")["sales"].sum().round(2).to_dict()
    rows = state.get("sql_result") or []
    actual = {}
    for row in rows:
        cat_key = next((k for k, v in row.items() if isinstance(v, str)), None)
        num_key = next((k for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
        if cat_key and num_key:
            actual[row[cat_key]] = row[num_key]
    if set(actual.keys()) != set(expected.keys()):
        return False, f"region sets differ — expected {set(expected.keys())}, got {set(actual.keys())}"
    for region, exp_val in expected.items():
        if not _close(actual[region], exp_val):
            return False, f"{region}: expected ~{exp_val}, got {actual[region]}"
    return True, f"matches ground truth ({expected})"


def check_correlation(state: dict, df: pd.DataFrame) -> tuple[bool, str]:
    expected = round(float(df["discount"].corr(df["quantity"])), 2)
    rows = state.get("sql_result") or []
    if not rows:
        return False, "no result rows"
    row = rows[0]
    actual = row.get("correlation", _first_numeric_value(row))
    if actual is None or not _close(actual, expected, tol=0.05):
        return False, f"expected ~{expected}, got {actual}"
    return True, f"matches ground truth ({expected})"


def check_must_fail(state: dict, df: pd.DataFrame) -> tuple[bool, str]:
    if state.get("validated") is False and state.get("status") == "rejected":
        return True, "correctly failed/rejected as expected"
    return False, f"expected a rejected/failed result, got validated={state.get('validated')} status={state.get('status')}"


def check_must_chart(state: dict, df: pd.DataFrame) -> tuple[bool, str]:
    if state.get("chart_path"):
        return True, f"chart generated at {state['chart_path']}"
    return False, f"no chart generated — chart_error={state.get('chart_error')}"


EVAL_CASES = [
    {"name": "total_revenue", "question": "What is the total revenue across all sales?", "check": check_total_revenue},
    {"name": "electronics_by_region", "question": "What is the total sales by region for the Electronics category?", "check": check_electronics_by_region},
    {"name": "discount_quantity_correlation", "question": "What is the correlation between discount and quantity sold?", "check": check_correlation},
    {"name": "nonsense_shoe_size", "question": "What is the average shoe size of our customers?", "check": check_must_fail},
    {"name": "chart_by_region", "question": "Show me a chart of total sales by region.", "check": check_must_chart},
]


def run():
    df = _ground_truth_df()
    graph = build_graph()

    results = []
    for case in EVAL_CASES:
        state = graph.invoke({
            "raw_query": case["question"],
            "dataset_name": "sales",
            "trace": [],
            "iteration_count": 0,
            "status": "pending",
        })

        passed, detail = case["check"](state, df)
        results.append({"name": case["name"], "check": "primary", "passed": passed, "detail": detail})

        # Universal consistency check — skip for expected-failure cases
        # (nothing meaningful to count) to avoid noisy false positives.
        if case["check"] is not check_must_fail:
            rows = state.get("sql_result") or []
            answer = state.get("final_answer") or ""
            consistent, c_detail = check_row_count_consistency(answer, len(rows))
            results.append({"name": case["name"], "check": "row_count_consistency", "passed": consistent, "detail": c_detail})

    print("=" * 70)
    print("EVAL RESULTS")
    print("=" * 70)
    n_pass = sum(r["passed"] for r in results)
    for r in results:
        status = "PASS ✅" if r["passed"] else "FAIL ❌"
        print(f"{status:10} | {r['name']:30} | {r['check']:22} | {r['detail']}")

    print()
    print("=" * 70)
    print(f"RESULT: {n_pass}/{len(results)} checks passed")
    print("=" * 70)


if __name__ == "__main__":
    run()
