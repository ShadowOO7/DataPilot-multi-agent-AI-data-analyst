"""
Business-term memory.

Small, fixed set of domain definitions stored in ChromaDB (persistent,
local — no API key, matches the project's no-paid-API pattern). Retrieved
by semantic search and injected into the SQL/Interpreter prompts so the
system grounds ambiguous business terms instead of guessing at them.

Concrete motivating case: this dataset has no cost-of-goods-sold data, so
"profit" can't actually be computed — only "revenue" (the sales column)
and "discount" exist. Without this context, the SQL Agent would happily
generate *some* query for a profit question and the Interpreter would
confidently narrate a wrong answer from it — exactly the kind of silent
wrong-answer this project has been hardening against all along (see
TESTING.md's column-mismatch bug for the same failure shape).

Relevance threshold: the first version always returned top-k=2 regardless
of how relevant they actually were (e.g. a shoe-size nonsense question
still pulled "order_id" and "revenue" notes as noise). Now filtered by
distance so an irrelevant question retrieves nothing rather than the
two least-bad matches. Set DEBUG_MEMORY=1 to print each query's actual
distances — the default _MAX_DISTANCE is an empirical starting point for
the default MiniLM embedding, not a value derived from this dataset;
tune it against real distances if it feels too strict or too loose.
"""

import os
from pathlib import Path

import chromadb

_CHROMA_PATH = Path(__file__).parent.parent / "chroma_data"
_COLLECTION_NAME = "business_terms"
_MAX_DISTANCE = 1.0  # empirical starting point — see module docstring

_SEED_TERMS = [
    {"id": "revenue", "text": "Revenue in this dataset is the 'sales' column — the gross transaction value recorded per order, before any discount is subtracted."},
    {"id": "profit", "text": "Profit CANNOT be computed from this dataset. There is no cost-of-goods-sold or expense data — only gross sales (revenue) and discount are tracked. Any question about profit, margin, or net income should be answered as not computable, not estimated."},
    {"id": "discount", "text": "Discount is stored as a decimal fraction (e.g. 0.05 means 5%), not a flat currency amount."},
    {"id": "region", "text": "Region is one of exactly four fixed sales territories: North, South, East, West."},
    {"id": "order", "text": "Each row in the sales table is a single order; order_id uniquely identifies it. There is no separate customer table — customer_id is just an identifier within this table."},
]


def _get_collection():
    client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    collection = client.get_or_create_collection(_COLLECTION_NAME)
    if collection.count() == 0:
        collection.add(
            ids=[t["id"] for t in _SEED_TERMS],
            documents=[t["text"] for t in _SEED_TERMS],
        )
    return collection


def retrieve_business_context(question: str, k: int = 2, max_distance: float = _MAX_DISTANCE) -> list[str]:
    """Semantic search over business term definitions relevant to the
    question, filtered by distance so an unrelated question returns
    nothing instead of forcing in the two least-irrelevant notes.

    Never raises — memory is an enhancement, and a broken or unavailable
    ChromaDB should degrade to 'no context' rather than taking down the
    whole pipeline."""
    try:
        collection = _get_collection()
        results = collection.query(query_texts=[question], n_results=k, include=["documents", "distances"])
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if os.getenv("DEBUG_MEMORY"):
            print(f"[memory] question={question!r} candidates={list(zip(docs, distances))}")

        return [doc for doc, dist in zip(docs, distances) if dist <= max_distance]
    except Exception:
        return []
