"""
Direct guardrail test for sql_tool_server.py's read-only enforcement.

This deliberately bypasses the LLM/SQL Agent — the Q4 adversarial test in
app/main.py showed the LLM just avoiding the injection on its own, which
proves nothing about whether the guardrail itself works. This script
sends known-malicious SQL straight to the MCP tool and checks it's
rejected, so the guardrail is proven independent of model behavior.

Run: python -m tests.test_sql_guardrail
"""

from pathlib import Path
from app.mcp_client import call_mcp_tool

_SQL_SERVER = str(Path(__file__).parent.parent / "app" / "mcp_servers" / "sql_tool_server.py")

MALICIOUS_QUERIES = [
    "DROP TABLE sales",
    "DELETE FROM sales WHERE 1=1",
    "UPDATE sales SET sales = 0",
    "INSERT INTO sales VALUES (1,2,3)",
    "SELECT * FROM sales; DROP TABLE sales",
    "ALTER TABLE sales ADD COLUMN hacked INT",
    "SELECT * FROM sales WHERE 1=1; DELETE FROM sales",
]

SAFE_QUERIES = [
    "SELECT * FROM sales LIMIT 5",
    "SELECT region, SUM(sales) FROM sales GROUP BY region",
    "WITH t AS (SELECT * FROM sales) SELECT * FROM t",
]


def run():
    print("=" * 60)
    print("MALICIOUS queries — every one of these MUST be blocked")
    print("=" * 60)
    all_blocked = True
    for q in MALICIOUS_QUERIES:
        result = call_mcp_tool(_SQL_SERVER, "execute_sql", {"query": q})
        error = result.get("error", "")
        blocked = error is not None and "[BLOCKED_SQL]" in str(error)
        status = "BLOCKED ✅" if blocked else "NOT BLOCKED ❌ — GUARDRAIL FAILED"
        if not blocked:
            all_blocked = False
        print(f"{status:30} | {q!r} -> {error}")

    print()
    print("=" * 60)
    print("SAFE queries — every one of these MUST succeed")
    print("=" * 60)
    all_passed = True
    for q in SAFE_QUERIES:
        result = call_mcp_tool(_SQL_SERVER, "execute_sql", {"query": q})
        error = result.get("error")
        ok = error is None
        status = "OK ✅" if ok else "FAILED ❌ — FALSE POSITIVE BLOCK"
        if not ok:
            all_passed = False
        print(f"{status:30} | {q!r} -> error={error}, rows={len(result.get('rows', []))}")

    print()
    print("=" * 60)
    if all_blocked and all_passed:
        print("RESULT: guardrail verified — malicious queries blocked, safe queries pass.")
    else:
        print("RESULT: guardrail has gaps — see ❌ lines above.")
    print("=" * 60)


if __name__ == "__main__":
    run()
