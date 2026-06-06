"""
Deterministic multi-agent quoting pipeline.

This gives the project an explicit Supervisor -> Retriever -> Pricing ->
Guardrail -> Quote Generator flow that can run without an LLM. The ADK agent
still exposes the same tools, while this pipeline is useful for tests,
evaluation, and production hardening.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from approval_queue import ApprovalQueue
from guardrails import guardrail_agent
from observability import Observability
from quote_storage import QuoteRepository
from rag_retriever import HistoricalQuoteRetriever


REQUEST_RE = re.compile(
    r"(?P<qty>\d+)\s+(?P<product>[A-Za-z ]+?)\s+for\s+(?P<customer>[A-Za-z0-9 &.-]+?)(?:,|\.|$)",
    re.IGNORECASE,
)


class SupervisorAgent:
    def __init__(
        self,
        data_dir: Path,
        approval_dir: Path,
        approved_dir: Path,
        telemetry_path: Path,
    ):
        self.repository = QuoteRepository(data_dir)
        self.retriever = HistoricalQuoteRetriever(data_dir / "historical_quotes.csv", data_dir / "vector_store")
        self.approval_queue = ApprovalQueue(approval_dir, approved_dir)
        self.telemetry = Observability(telemetry_path)

    def run(self, user_request: str, customer_type: str = "regular") -> Dict[str, Any]:
        with self.telemetry.span("supervisor_agent", request=user_request):
            parsed = RetrieverAgent().parse_request(user_request)
            if not parsed["ok"]:
                return parsed

            historical_context = self.retriever.search(
                f"{parsed['customer']} {parsed['product']} {parsed['qty']}", top_k=3
            )

            priced = PricingAgent(self.repository).price(
                product_name=parsed["product"],
                qty=parsed["qty"],
                customer_type=customer_type,
            )
            if not priced["ok"]:
                return priced

            validation = ValidationAgent(self.repository).validate(user_request, priced)
            quote = QuoteGeneratorAgent(self.approval_queue).generate(
                customer=parsed["customer"],
                items=[priced["item"]],
                terms="Standard T&C apply.",
                historical_context=historical_context,
                guardrails=validation,
            )
            self.repository.update_customer_memory(parsed["customer"], quote)
            return quote


class RetrieverAgent:
    def parse_request(self, user_request: str) -> Dict[str, Any]:
        match = REQUEST_RE.search(user_request)
        if not match:
            return {
                "ok": False,
                "agent": "RetrieverAgent",
                "message": "Please include quantity, product, and customer, for example: 50 Office Chairs for ABC Corp.",
            }
        return {
            "ok": True,
            "agent": "RetrieverAgent",
            "qty": int(match.group("qty")),
            "product": match.group("product").strip(),
            "customer": match.group("customer").strip(),
        }


class PricingAgent:
    def __init__(self, repository: QuoteRepository):
        self.repository = repository

    def price(self, product_name: str, qty: int, customer_type: str) -> Dict[str, Any]:
        product = self.repository.find_product(product_name)
        if not product:
            available = ", ".join(item["name"] for item in self.repository.list_products())
            return {
                "ok": False,
                "agent": "PricingAgent",
                "message": f"No product matching '{product_name}'. Available products: {available}",
            }

        discount_pct = 0.15 if qty >= 100 else 0.10 if qty >= 50 else 0.05 if qty >= 20 else 0.0
        if customer_type == "preferred":
            discount_pct += 0.05
        unit_price = float(product["unit_price"])
        total = unit_price * qty * (1 - discount_pct)
        return {
            "ok": True,
            "agent": "PricingAgent",
            "discount_pct": discount_pct,
            "item": {
                "name": product["name"],
                "sku": product["sku"],
                "qty": qty,
                "unit_price": unit_price,
                "discount_pct": discount_pct,
                "total": total,
            },
        }


class ValidationAgent:
    def __init__(self, repository: QuoteRepository):
        self.repository = repository

    def validate(self, user_request: str, priced: Dict[str, Any]) -> Dict[str, Any]:
        products = [product["name"] for product in self.repository.list_products()]
        return guardrail_agent(
            request_text=user_request,
            items=[priced["item"]],
            discount_pct=priced["discount_pct"],
            known_products=products,
            total=priced["item"]["total"],
        )


class QuoteGeneratorAgent:
    def __init__(self, approval_queue: ApprovalQueue):
        self.approval_queue = approval_queue

    def generate(
        self,
        customer: str,
        items: List[Dict[str, Any]],
        terms: str,
        historical_context: List[Dict[str, Any]],
        guardrails: Dict[str, Any],
    ) -> Dict[str, Any]:
        subtotal = sum(item["unit_price"] * item["qty"] for item in items)
        total = sum(item["total"] for item in items)
        quote = {
            "ok": True,
            "agent": "QuoteGeneratorAgent",
            "quote_id": f"Q-{uuid.uuid4().hex[:6].upper()}",
            "customer": customer,
            "items": items,
            "subtotal": subtotal,
            "total": total,
            "terms": terms,
            "historical_context": historical_context,
            "guardrails": guardrails,
        }
        return self.approval_queue.submit(quote)
