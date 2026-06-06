"""
Storage adapters for the quoting agent.

The app can run from the existing CSV files for demos. When DATABASE_URL is set
and psycopg is installed, the same repository reads from PostgreSQL tables:
products, customers, quotes, and discount_rules.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit_price NUMERIC NOT NULL,
    tier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    customer_type TEXT NOT NULL DEFAULT 'regular',
    preferred_discounts JSONB NOT NULL DEFAULT '{}'::jsonb,
    purchase_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    past_conversations JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS discount_rules (
    id SERIAL PRIMARY KEY,
    rule_name TEXT NOT NULL,
    min_qty INTEGER NOT NULL DEFAULT 0,
    customer_type TEXT,
    discount_pct NUMERIC NOT NULL,
    max_discount_pct NUMERIC NOT NULL DEFAULT 0.20,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS quotes (
    quote_id TEXT PRIMARY KEY,
    customer TEXT NOT NULL,
    items JSONB NOT NULL,
    subtotal NUMERIC NOT NULL,
    total NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_approval',
    terms TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ
);
"""


class QuoteRepository:
    """Repository with PostgreSQL support and CSV/JSON fallback."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.products_csv = data_dir / "products.csv"
        self.customers_json = data_dir / "customer_memory.json"
        self.quotes_log_csv = data_dir / "quotes_log.csv"
        self.database_url = os.getenv("DATABASE_URL")
        self._pg = None

        if self.database_url:
            try:
                import psycopg

                self._pg = psycopg
            except ImportError:
                self._pg = None

    @property
    def using_postgres(self) -> bool:
        return bool(self.database_url and self._pg)

    def initialize_postgres(self) -> bool:
        if not self.using_postgres:
            return False
        with self._pg.connect(self.database_url) as conn:
            conn.execute(SCHEMA_SQL)
        return True

    def list_products(self) -> List[Dict[str, Any]]:
        if self.using_postgres:
            with self._pg.connect(self.database_url) as conn:
                rows = conn.execute(
                    "SELECT sku, name, unit_price, tier FROM products ORDER BY name"
                ).fetchall()
            return [
                {
                    "sku": row[0],
                    "name": row[1],
                    "unit_price": float(row[2]),
                    "tier": row[3],
                }
                for row in rows
            ]

        return pd.read_csv(self.products_csv).to_dict(orient="records")

    def find_product(self, product_name: str) -> Optional[Dict[str, Any]]:
        needle = product_name.lower().strip()
        singular = needle.rstrip("s")
        products = self.list_products()
        for product in products:
            haystack = product["name"].lower()
            if needle in haystack or singular in haystack or haystack.rstrip("s") in needle:
                product["unit_price"] = float(product["unit_price"])
                return product
        return None

    def get_customer_memory(self, customer: str) -> Dict[str, Any]:
        if self.using_postgres:
            with self._pg.connect(self.database_url) as conn:
                row = conn.execute(
                    """
                    SELECT name, customer_type, preferred_discounts,
                           purchase_history, past_conversations
                    FROM customers
                    WHERE lower(name) = lower(%s)
                    """,
                    (customer,),
                ).fetchone()
            if row:
                return {
                    "customer": row[0],
                    "customer_type": row[1],
                    "preferred_discounts": row[2],
                    "purchase_history": row[3],
                    "past_conversations": row[4],
                }

        memory = self._load_customer_memory()
        return memory.get(
            customer.lower(),
            {
                "customer": customer,
                "customer_type": "regular",
                "preferred_discounts": {},
                "purchase_history": [],
                "past_conversations": [],
            },
        )

    def update_customer_memory(self, customer: str, quote: Dict[str, Any]) -> None:
        if self.using_postgres:
            with self._pg.connect(self.database_url) as conn:
                conn.execute(
                    """
                    INSERT INTO customers (name, purchase_history)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (name) DO UPDATE
                    SET purchase_history = customers.purchase_history || EXCLUDED.purchase_history
                    """,
                    (customer, json.dumps([quote])),
                )
            return

        memory = self._load_customer_memory()
        key = customer.lower()
        record = memory.setdefault(
            key,
            {
                "customer": customer,
                "customer_type": "regular",
                "preferred_discounts": {},
                "purchase_history": [],
                "past_conversations": [],
            },
        )
        record["purchase_history"].append(
            {
                "quote_id": quote["quote_id"],
                "total": quote["total"],
                "items": quote["items"],
                "status": quote["status"],
            }
        )
        self.customers_json.write_text(json.dumps(memory, indent=2), encoding="utf-8")

    def _load_customer_memory(self) -> Dict[str, Any]:
        if self.customers_json.exists():
            return json.loads(self.customers_json.read_text(encoding="utf-8"))
        return {}
