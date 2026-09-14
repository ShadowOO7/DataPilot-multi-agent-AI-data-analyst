"""
Observability.

Two pieces, deliberately different in how "real" they are:

1. Local trace logging — always works, no external account needed. Every
   run's full state (plan, trace, SQL, results, final answer) is dumped
   to outputs/traces/ as JSON. This is the actual usable observability
   for local/offline development.

2. Langfuse — only activates if LANGFUSE_PUBLIC_KEY and
   LANGFUSE_SECRET_KEY are set in the environment. Wired once, centrally,
   in app/llm.py's get_llm() (every agent already calls that, so this is
   the one place tracing needs to be attached rather than touching every
   agent file). Skipped cleanly with no error if not configured — this
   project should never require a paid/external account to run.
"""

import json
import os
import time
from pathlib import Path

_TRACE_DIR = Path(__file__).parent.parent / "outputs" / "traces"


def _is_json_safe(v) -> bool:
    try:
        json.dumps(v, default=str)
        return True
    except TypeError:
        return False


def save_trace(state: dict, query_name: str) -> str:
    """Dump a run's full state to outputs/traces/<timestamp>_<name>.json.
    Never raises — a broken trace write shouldn't take down the run."""
    try:
        _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() else "_" for c in query_name)[:50]
        filename = f"{int(time.time() * 1000)}_{safe_name}.json"
        path = _TRACE_DIR / filename
        safe_state = {k: v for k, v in state.items() if _is_json_safe(v)}
        with open(path, "w") as f:
            json.dump(safe_state, f, indent=2, default=str)
        return str(path)
    except Exception as e:
        return f"[TRACE_WRITE_FAILED] {type(e).__name__}: {e}"


def get_langfuse_handler():
    """Returns a Langfuse callback handler if credentials are configured,
    else None. Never raises — Langfuse is an optional enhancement, not a
    dependency of the pipeline running at all."""
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception:
        return None
