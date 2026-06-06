"""
Historical quote RAG retriever.

This builds deterministic lightweight embeddings from historical_quotes.csv and
persists them as a local vector index. FAISS or Chroma can replace this class
without changing the retriever tool contract.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List


TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
VECTOR_SIZE = 128


def chunk_quote(row: Dict[str, str]) -> str:
    return (
        f"Quote {row.get('quote_id')} for {row.get('customer')}: "
        f"{row.get('qty')} x {row.get('product')} at {row.get('unit_price')} "
        f"total {row.get('total')}. Accepted: {row.get('accepted')}. "
        f"Notes: {row.get('notes', '')}"
    )


def embed_text(text: str) -> List[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % VECTOR_SIZE
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: List[float], right: List[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class HistoricalQuoteRetriever:
    def __init__(self, history_csv: Path, index_dir: Path):
        self.history_csv = history_csv
        self.index_dir = index_dir
        self.index_path = index_dir / "historical_quotes.index.json"
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def build_index(self) -> Dict[str, Any]:
        records = []
        with open(self.history_csv, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                chunk = chunk_quote(row)
                records.append(
                    {
                        "chunk": chunk,
                        "embedding": embed_text(chunk),
                        "metadata": row,
                    }
                )

        payload = {
            "source": str(self.history_csv),
            "store": "local_vector_store",
            "embedding_model": "deterministic_hash_embedding",
            "records": records,
        }
        self.index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"indexed_chunks": len(records), "index_path": str(self.index_path)}

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            self.build_index()

        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        query_embedding = embed_text(query)
        scored = []
        for record in payload.get("records", []):
            score = cosine(query_embedding, record["embedding"])
            scored.append(
                {
                    "score": round(score, 4),
                    "chunk": record["chunk"],
                    "metadata": record["metadata"],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]
