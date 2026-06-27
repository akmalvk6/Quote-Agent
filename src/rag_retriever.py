"""
Historical quote RAG retriever.

Uses Gemini Embeddings (gemini-embedding-001) for semantic vector
representations and ChromaDB as the persistent vector store.

Falls back to deterministic hash embeddings when no API key is available.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Chunking helper (unchanged)
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def chunk_quote(row: Dict[str, str]) -> str:
    return (
        f"Quote {row.get('quote_id')} for {row.get('customer')}: "
        f"{row.get('qty')} x {row.get('product')} at {row.get('unit_price')} "
        f"total {row.get('total')}. Accepted: {row.get('accepted')}. "
        f"Notes: {row.get('notes', '')}"
    )


# ---------------------------------------------------------------------------
# Gemini Embedder
# ---------------------------------------------------------------------------

def _resolve_api_key() -> Optional[str]:
    """Return the first available Gemini / Google API key."""
    for var in ("GOOGLE_API_KEY", "AGENTX_GEMINI_API_KEY"):
        key = os.getenv(var)
        if key:
            return key
    return None


class GeminiEmbedder:
    """Wraps the google-genai SDK to produce embeddings via Gemini."""

    MODEL = "gemini-embedding-001"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or _resolve_api_key()
        self._client = None
        if self._api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=self._api_key)
            except ImportError:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of document texts for storage / retrieval."""
        if not self._client:
            raise RuntimeError("Gemini client is not initialised – missing API key or google-genai package")
        from google.genai import types as genai_types

        result = self._client.models.embed_content(
            model=self.MODEL,
            contents=texts,
            config=genai_types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        return [list(e.values) for e in result.embeddings]

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text for similarity search."""
        if not self._client:
            raise RuntimeError("Gemini client is not initialised – missing API key or google-genai package")
        from google.genai import types as genai_types

        result = self._client.models.embed_content(
            model=self.MODEL,
            contents=[text],
            config=genai_types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        return list(result.embeddings[0].values)


# ---------------------------------------------------------------------------
# Hash-based fallback (original lightweight implementation)
# ---------------------------------------------------------------------------

HASH_VECTOR_SIZE = 128


def _hash_embed_text(text: str) -> List[float]:
    """Deterministic hash-based embedding – used when Gemini is unavailable."""
    vector = [0.0] * HASH_VECTOR_SIZE
    for token in TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % HASH_VECTOR_SIZE
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _cosine(left: List[float], right: List[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


# ---------------------------------------------------------------------------
# ChromaDB embedding function adapter
# ---------------------------------------------------------------------------

class _ChromaGeminiEmbeddingFunction:
    """Adapter so ChromaDB can call Gemini directly during add/query."""

    def __init__(self, embedder: GeminiEmbedder):
        self._embedder = embedder

    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self._embedder.embed_documents(input)


# ---------------------------------------------------------------------------
# Historical Quote Retriever  (public API unchanged)
# ---------------------------------------------------------------------------

class HistoricalQuoteRetriever:
    """
    Reads historical quotes from CSV and provides semantic search.

    When Gemini + ChromaDB are available the retriever uses real embeddings
    stored in a persistent ChromaDB collection.  Otherwise it falls back to
    the original hash-based in-memory approach.
    """

    COLLECTION_NAME = "historical_quotes"

    def __init__(self, history_csv: Path, index_dir: Path):
        self.history_csv = history_csv
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # Try to initialise Gemini + ChromaDB
        self._embedder = GeminiEmbedder()
        self._chroma_client = None
        self._collection = None
        self._use_chroma = False

        if self._embedder.available:
            try:
                import chromadb

                chroma_path = self.index_dir / "chroma_store"
                chroma_path.mkdir(parents=True, exist_ok=True)
                self._chroma_client = chromadb.PersistentClient(path=str(chroma_path))
                self._collection = self._chroma_client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=_ChromaGeminiEmbeddingFunction(self._embedder),
                )
                self._use_chroma = True
            except ImportError:
                self._use_chroma = False

        # Fallback data (populated lazily)
        self._fallback_records: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Build / rebuild the index
    # ------------------------------------------------------------------

    def build_index(self) -> Dict[str, Any]:
        rows = self._read_csv()
        if not rows:
            return {"indexed_chunks": 0}

        if self._use_chroma:
            return self._build_chroma_index(rows)
        return self._build_fallback_index(rows)

    def _read_csv(self) -> List[Dict[str, str]]:
        if not self.history_csv.exists():
            return []
        with open(self.history_csv, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def _build_chroma_index(self, rows: List[Dict[str, str]]) -> Dict[str, Any]:
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, str]] = []

        for row in rows:
            doc_id = row.get("quote_id", "")
            chunk = chunk_quote(row)
            ids.append(doc_id)
            documents.append(chunk)
            metadatas.append(row)

        # Upsert (idempotent – safe to re-run)
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        return {
            "indexed_chunks": len(ids),
            "store": "chromadb",
            "embedding_model": GeminiEmbedder.MODEL,
            "collection": self.COLLECTION_NAME,
        }

    def _build_fallback_index(self, rows: List[Dict[str, str]]) -> Dict[str, Any]:
        self._fallback_records = []
        for row in rows:
            chunk = chunk_quote(row)
            self._fallback_records.append(
                {"chunk": chunk, "embedding": _hash_embed_text(chunk), "metadata": row}
            )
        return {
            "indexed_chunks": len(self._fallback_records),
            "store": "in_memory_hash",
            "embedding_model": "deterministic_hash_embedding",
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if self._use_chroma:
            return self._search_chroma(query, top_k)
        return self._search_fallback(query, top_k)

    def _search_chroma(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        # Ensure index exists
        if self._collection.count() == 0:
            self.build_index()
            if self._collection.count() == 0:
                return []

        query_embedding = self._embedder.embed_query(query)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        scored: List[Dict[str, Any]] = []
        for i in range(len(results["ids"][0])):
            # ChromaDB returns distances; for cosine space, similarity = 1 - distance
            distance = results["distances"][0][i] if results["distances"] else 0.0
            scored.append(
                {
                    "score": round(1.0 - distance, 4),
                    "chunk": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                }
            )
        return scored

    def _search_fallback(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._fallback_records is None:
            self.build_index()
        if not self._fallback_records:
            return []

        query_embedding = _hash_embed_text(query)
        scored = []
        for record in self._fallback_records:
            score = _cosine(query_embedding, record["embedding"])
            scored.append(
                {"score": round(score, 4), "chunk": record["chunk"], "metadata": record["metadata"]}
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]
