"""
Product Discovery module with RAG-based semantic search.

Uses ChromaDB + Gemini Embeddings to find the closest matching products
when an exact name match fails.  Implements confidence-tiered matching:

    Score >= 0.85   →  Auto-select the product
    0.70 – 0.84     →  Present candidates, ask the user to choose
    < 0.70          →  No match found

Price is deliberately excluded from the embedding text so that it does
not pollute the semantic vector space.  It is stored as ChromaDB metadata
and returned alongside search results.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from rag_retriever import (
    GeminiEmbedder,
    _ChromaGeminiEmbeddingFunction,
    _cosine,
    _hash_embed_text,
)

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

AUTO_SELECT_THRESHOLD = 0.85
ASK_USER_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_product_document(row: Dict[str, str]) -> str:
    """Build a rich-text document for embedding.  Price is *excluded*."""
    parts = [f"Product: {row.get('name', '')}"]

    if row.get("category"):
        parts.append(f"Category: {row['category']}")
    if row.get("description"):
        parts.append(f"Description: {row['description']}")
    if row.get("dimensions"):
        parts.append(f"Dimensions: {row['dimensions']}")
    if row.get("features"):
        parts.append(f"Features: {row['features'].replace(';', ', ')}")
    if row.get("use_cases"):
        parts.append(f"Use Cases: {row['use_cases'].replace(';', ', ')}")
    if row.get("keywords"):
        parts.append(f"Keywords: {row['keywords'].replace(';', ', ')}")

    return "\n".join(parts)


def _metadata_from_row(row: Dict[str, str]) -> Dict[str, str]:
    """Extract metadata fields stored alongside the vector (includes price)."""
    return {
        "sku": row.get("sku", ""),
        "name": row.get("name", ""),
        "unit_price": str(row.get("unit_price", "")),
        "tier": row.get("tier", ""),
        "category": row.get("category", ""),
    }


# ---------------------------------------------------------------------------
# ProductDiscovery
# ---------------------------------------------------------------------------


class ProductDiscovery:
    """
    Semantic product search backed by ChromaDB + Gemini Embeddings.

    Falls back to hash-based in-memory search when Gemini / ChromaDB are
    not available.
    """

    COLLECTION_NAME = "product_catalog"

    def __init__(self, products_csv: Path, index_dir: Path):
        self.products_csv = products_csv
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)

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

        # Fallback data
        self._fallback_records: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self) -> Dict[str, Any]:
        """Read products.csv, embed, and upsert into ChromaDB."""
        rows = self._read_csv()
        if not rows:
            return {"ingested": 0}

        if self._use_chroma:
            return self._ingest_chroma(rows)
        return self._ingest_fallback(rows)

    def _read_csv(self) -> List[Dict[str, str]]:
        if not self.products_csv.exists():
            return []
        with open(self.products_csv, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def _ingest_chroma(self, rows: List[Dict[str, str]]) -> Dict[str, Any]:
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, str]] = []

        for row in rows:
            doc_id = row.get("sku", row.get("name", ""))
            document = _build_product_document(row)
            ids.append(doc_id)
            documents.append(document)
            metadatas.append(_metadata_from_row(row))

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        return {
            "ingested": len(ids),
            "store": "chromadb",
            "collection": self.COLLECTION_NAME,
            "embedding_model": GeminiEmbedder.MODEL,
        }

    def _ingest_fallback(self, rows: List[Dict[str, str]]) -> Dict[str, Any]:
        self._fallback_records = []
        for row in rows:
            document = _build_product_document(row)
            self._fallback_records.append(
                {
                    "document": document,
                    "embedding": _hash_embed_text(document),
                    "metadata": _metadata_from_row(row),
                }
            )
        return {
            "ingested": len(self._fallback_records),
            "store": "in_memory_hash",
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def find_similar(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Return top-k products ranked by semantic similarity."""
        if self._use_chroma:
            return self._search_chroma(query, top_k)
        return self._search_fallback(query, top_k)

    def _search_chroma(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._collection.count() == 0:
            self.ingest()
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
            distance = results["distances"][0][i] if results["distances"] else 0.0
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            scored.append(
                {
                    "product_name": meta.get("name", ""),
                    "score": round(1.0 - distance, 4),
                    "sku": meta.get("sku", ""),
                    "unit_price": float(meta.get("unit_price", 0)),
                    "tier": meta.get("tier", ""),
                    "category": meta.get("category", ""),
                }
            )
        return scored

    def _search_fallback(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._fallback_records is None:
            self.ingest()
        if not self._fallback_records:
            return []

        query_embedding = _hash_embed_text(query)
        scored = []
        for record in self._fallback_records:
            score = _cosine(query_embedding, record["embedding"])
            meta = record["metadata"]
            scored.append(
                {
                    "product_name": meta.get("name", ""),
                    "score": round(score, 4),
                    "sku": meta.get("sku", ""),
                    "unit_price": float(meta.get("unit_price", 0)),
                    "tier": meta.get("tier", ""),
                    "category": meta.get("category", ""),
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------
    # Confidence-tiered matching
    # ------------------------------------------------------------------

    def find_or_match(
        self, product_name: str, repository: Any
    ) -> Dict[str, Any]:
        """
        Try exact match first, then fall back to semantic search with
        confidence-tiered logic.

        Returns a ``DiscoveryResult`` dict with ``match_type`` of:
        - ``"exact"``     – product found by name
        - ``"auto"``      – top score >= 0.85, safe to auto-select
        - ``"ask_user"``  – top score 0.70–0.84, present candidates
        - ``"no_match"``  – top score < 0.70, reject
        """
        # --- exact match ---
        product = repository.find_product(product_name)
        if product:
            return {
                "match_type": "exact",
                "product": product,
                "requested_product": product_name,
                "matched_product": product["name"],
                "match_score": 1.0,
                "candidates": [],
            }

        # --- semantic search ---
        candidates = self.find_similar(product_name, top_k=3)
        if not candidates:
            available = ", ".join(p["name"] for p in repository.list_products())
            return {
                "match_type": "no_match",
                "product": None,
                "requested_product": product_name,
                "matched_product": None,
                "match_score": 0.0,
                "candidates": [],
                "message": (
                    f"No matching product found for '{product_name}'. "
                    f"Available products: {available}"
                ),
            }

        top = candidates[0]
        top_score = top["score"]

        if top_score >= AUTO_SELECT_THRESHOLD:
            # Re-fetch full product record from repository for consistency
            matched_product = repository.find_product(top["product_name"])
            return {
                "match_type": "auto",
                "product": matched_product or {
                    "name": top["product_name"],
                    "sku": top["sku"],
                    "unit_price": top["unit_price"],
                    "tier": top["tier"],
                },
                "requested_product": product_name,
                "matched_product": top["product_name"],
                "match_score": top_score,
                "candidates": candidates,
                "message": (
                    f"No exact match for '{product_name}'. "
                    f"The closest product is '{top['product_name']}' "
                    f"({int(top_score * 100)}% match). "
                    f"The quote has been generated using this product."
                ),
            }

        if top_score >= ASK_USER_THRESHOLD:
            lines = [f"I couldn't find an exact product for '{product_name}'. Did you mean:"]
            for idx, c in enumerate(candidates, 1):
                if c["score"] >= ASK_USER_THRESHOLD:
                    lines.append(f"  {idx}. {c['product_name']} ({int(c['score'] * 100)}% match)")
            lines.append("\nPlease specify which product to use.")
            return {
                "match_type": "ask_user",
                "product": None,
                "requested_product": product_name,
                "matched_product": None,
                "match_score": top_score,
                "candidates": candidates,
                "message": "\n".join(lines),
            }

        # --- no match ---
        available = ", ".join(p["name"] for p in repository.list_products())
        return {
            "match_type": "no_match",
            "product": None,
            "requested_product": product_name,
            "matched_product": None,
            "match_score": top_score,
            "candidates": candidates,
            "message": (
                f"No matching product found for '{product_name}' "
                f"(best match was '{top['product_name']}' at "
                f"{int(top_score * 100)}% which is below the 70% threshold). "
                f"Available products: {available}"
            ),
        }
