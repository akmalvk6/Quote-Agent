#!/usr/bin/env python
"""
Product catalog ingestion script.

Reads products.csv, generates Gemini embeddings for each product document,
and stores the vectors in ChromaDB.  Price is excluded from the embedding
text and stored only as metadata.

Usage
-----
    python ingest_products.py                     # default CSV
    python ingest_products.py --csv path/to.csv   # custom CSV
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from product_discovery import ProductDiscovery


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest product catalog into ChromaDB vector store."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "products.csv",
        help="Path to the products CSV file (default: data/products.csv)",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "vector_store",
        help="Directory for ChromaDB persistence (default: data/vector_store)",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"❌ Products CSV not found: {args.csv}")
        sys.exit(1)

    print(f"📦 Reading products from: {args.csv}")
    print(f"💾 Vector store directory: {args.index_dir}")

    discovery = ProductDiscovery(args.csv, args.index_dir)
    result = discovery.ingest()

    print(f"\n✅ Ingestion complete:")
    print(json.dumps(result, indent=2))

    # Quick verification — search for a sample query
    print("\n🔍 Verification — searching for 'study table':")
    matches = discovery.find_similar("study table", top_k=3)
    for match in matches:
        print(f"   • {match['product_name']} — score: {match['score']:.4f}")


if __name__ == "__main__":
    main()
