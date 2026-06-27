"""
LangGraph-based quote orchestration pipeline.

Replaces the sequential ``SupervisorAgent.run()`` with an explicit
LangGraph StateGraph whose nodes mirror the original agent classes:

    parse_request  →  retrieve_history  →  price_items
                                              ↓
                                        validate_quote  →  generate_quote

Conditional edges route errors to END early.

Usage
-----
    from langgraph_orchestrator import LangGraphQuoteOrchestrator

    orchestrator = LangGraphQuoteOrchestrator(data_dir, approval_dir, approved_dir, telemetry_path)
    result = orchestrator.run("50 Office Chairs for TestCorp")
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from langchain_core.runnables.graph import MermaidDrawMethod
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict

from approval_queue import ApprovalQueue
from guardrails import guardrail_agent
from llm_extractor import LLMExtractor, QuoteRequest
from observability import Observability
from product_discovery import ProductDiscovery
from quote_storage import QuoteRepository
from rag_retriever import HistoricalQuoteRetriever

# ---------------------------------------------------------------------------
# Request parser (structured LLM extraction with regex fallback)
# ---------------------------------------------------------------------------

_extractor = LLMExtractor()

# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class QuoteState(TypedDict, total=False):
    """Typed state flowing through the LangGraph pipeline."""

    # Inputs
    user_request: str
    customer_type: str

    # parse_request outputs
    parsed_ok: bool
    parsed_qty: int
    parsed_product: str
    parsed_customer: str

    # retrieve_history outputs
    historical_context: List[Dict[str, Any]]

    # price_items outputs
    priced_ok: bool
    priced_item: Dict[str, Any]
    priced_discount_pct: float

    # discover_product outputs
    discovery_match_type: Optional[str]
    requested_product: Optional[str]
    matched_product: Optional[str]
    match_score: Optional[float]
    discovery_message: Optional[str]

    # validate_quote outputs
    validation: Dict[str, Any]

    # generate_quote outputs
    quote: Dict[str, Any]

    # Error tracking
    error: Optional[str]
    error_agent: Optional[str]


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def _parse_request(state: QuoteState) -> dict:
    """Extract qty, product and customer using structured LLM extraction."""
    result: QuoteRequest | None = _extractor.extract(state["user_request"])
    if result is None:
        return {
            "parsed_ok": False,
            "error": "Could not parse request. Please include quantity, product, and customer, for example: 50 Office Chairs for ABC Corp.",
            "error_agent": "RetrieverAgent",
        }
    return {
        "parsed_ok": True,
        "parsed_qty": result.quantity,
        "parsed_product": result.product,
        "parsed_customer": result.customer,
        "customer_type": result.customer_type,
    }


def _after_parse(state: QuoteState) -> str:
    """Conditional edge: continue if parse succeeded, otherwise end."""
    return "retrieve_history" if state.get("parsed_ok") else END


def _retrieve_history(state: QuoteState) -> dict:
    """Query the vector store for similar historical quotes."""
    retriever: HistoricalQuoteRetriever = state["_retriever"]  # type: ignore[typeddict-item]
    query = f"{state['parsed_customer']} {state['parsed_product']} {state['parsed_qty']}"
    results = retriever.search(query, top_k=3)
    return {"historical_context": results}


def _discover_product(state: QuoteState) -> dict:
    """Try exact product match, then fall back to semantic search."""
    repository: QuoteRepository = state["_repository"]  # type: ignore[typeddict-item]
    discovery: ProductDiscovery = state["_product_discovery"]  # type: ignore[typeddict-item]
    product_name = state["parsed_product"]

    result = discovery.find_or_match(product_name, repository)
    match_type = result["match_type"]

    if match_type in ("exact", "auto"):
        # Overwrite parsed_product with the actual product name
        update: dict = {
            "parsed_product": result["product"]["name"],
            "discovery_match_type": match_type,
            "requested_product": result["requested_product"],
            "matched_product": result["matched_product"],
            "match_score": result["match_score"],
        }
        if match_type == "auto":
            update["discovery_message"] = result.get("message", "")
        return update

    # ask_user or no_match — route to END
    return {
        "discovery_match_type": match_type,
        "requested_product": result["requested_product"],
        "match_score": result.get("match_score", 0.0),
        "error": result.get("message", "Product not found."),
        "error_agent": "ProductDiscoveryAgent",
    }


def _after_discovery(state: QuoteState) -> str:
    """Conditional edge: continue only if exact or auto match."""
    match_type = state.get("discovery_match_type", "no_match")
    if match_type in ("exact", "auto"):
        return "price_items"
    return END


def _price_items(state: QuoteState) -> dict:
    """Look up the product and calculate discounted pricing."""
    repository: QuoteRepository = state["_repository"]  # type: ignore[typeddict-item]
    product_name = state["parsed_product"]
    qty = state["parsed_qty"]
    customer_type = state.get("customer_type", "regular")

    product = repository.find_product(product_name)
    if not product:
        available = ", ".join(item["name"] for item in repository.list_products())
        return {
            "priced_ok": False,
            "error": f"No product matching '{product_name}'. Available products: {available}",
            "error_agent": "PricingAgent",
        }

    discount_pct = 0.15 if qty >= 100 else 0.10 if qty >= 50 else 0.05 if qty >= 20 else 0.0
    if customer_type == "preferred":
        discount_pct += 0.05

    unit_price = float(product["unit_price"])
    total = unit_price * qty * (1 - discount_pct)
    item = {
        "name": product["name"],
        "sku": product["sku"],
        "qty": qty,
        "unit_price": unit_price,
        "discount_pct": discount_pct,
        "total": total,
    }
    return {"priced_ok": True, "priced_item": item, "priced_discount_pct": discount_pct}


def _after_price(state: QuoteState) -> str:
    """Conditional edge: continue if pricing succeeded, otherwise end."""
    return "validate_quote" if state.get("priced_ok") else END


def _validate_quote(state: QuoteState) -> dict:
    """Run guardrail checks on the priced quote."""
    repository: QuoteRepository = state["_repository"]  # type: ignore[typeddict-item]
    known_products = [p["name"] for p in repository.list_products()]
    validation = guardrail_agent(
        request_text=state["user_request"],
        items=[state["priced_item"]],
        discount_pct=state["priced_discount_pct"],
        known_products=known_products,
        total=state["priced_item"]["total"],
    )
    return {"validation": validation}


def _generate_quote(state: QuoteState) -> dict:
    """Create the quote document and submit it to the approval queue."""
    approval: ApprovalQueue = state["_approval_queue"]  # type: ignore[typeddict-item]
    repository: QuoteRepository = state["_repository"]  # type: ignore[typeddict-item]
    item = state["priced_item"]

    subtotal = item["unit_price"] * item["qty"]
    total = item["total"]
    quote = {
        "ok": True,
        "agent": "QuoteGeneratorAgent",
        "quote_id": f"Q-{uuid.uuid4().hex[:6].upper()}",
        "customer": state["parsed_customer"],
        "items": [item],
        "subtotal": subtotal,
        "total": total,
        "terms": "Standard T&C apply.",
        "historical_context": state.get("historical_context", []),
        "guardrails": state.get("validation", {}),
    }

    # Include product discovery metadata when semantic fallback was used
    if state.get("discovery_match_type") == "auto":
        quote["requested_product"] = state.get("requested_product", "")
        quote["matched_product"] = state.get("matched_product", "")
        quote["match_score"] = state.get("match_score", 0.0)

    submitted = approval.submit(quote)
    repository.update_customer_memory(state["parsed_customer"], submitted)
    return {"quote": submitted}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _build_graph() -> StateGraph:
    """Construct and compile the LangGraph quote pipeline."""
    graph = StateGraph(dict)  # use plain dict as state type for flexibility

    # --- nodes ---
    graph.add_node("parse_request", _parse_request)
    graph.add_node("retrieve_history", _retrieve_history)
    graph.add_node("discover_product", _discover_product)
    graph.add_node("price_items", _price_items)
    graph.add_node("validate_quote", _validate_quote)
    graph.add_node("generate_quote", _generate_quote)

    # --- edges ---
    graph.set_entry_point("parse_request")
    graph.add_conditional_edges("parse_request", _after_parse, {"retrieve_history": "retrieve_history", END: END})
    graph.add_edge("retrieve_history", "discover_product")
    graph.add_conditional_edges("discover_product", _after_discovery, {"price_items": "price_items", END: END})
    graph.add_conditional_edges("price_items", _after_price, {"validate_quote": "validate_quote", END: END})
    graph.add_edge("validate_quote", "generate_quote")
    graph.add_edge("generate_quote", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public orchestrator class (drop-in replacement for SupervisorAgent)
# ---------------------------------------------------------------------------


class LangGraphQuoteOrchestrator:
    """
    LangGraph-based orchestrator for the quoting pipeline.

    Constructor and ``run()`` signatures match ``SupervisorAgent`` so this
    can be used as a drop-in replacement.
    """

    def __init__(
        self,
        data_dir: Path,
        approval_dir: Path,
        approved_dir: Path,
        telemetry_path: Path,
    ):
        self.repository = QuoteRepository(data_dir)
        self.retriever = HistoricalQuoteRetriever(
            data_dir / "historical_quotes.csv",
            data_dir / "vector_store",
        )
        self.product_discovery = ProductDiscovery(
            data_dir / "products.csv",
            data_dir / "vector_store",
        )
        self.approval_queue = ApprovalQueue(approval_dir, approved_dir)
        self.telemetry = Observability(telemetry_path)
        self._compiled_graph = _build_graph()

    def run(self, user_request: str, customer_type: str = "regular") -> Dict[str, Any]:
        """Execute the full quoting pipeline and return the result dict."""
        with self.telemetry.span("langgraph_orchestrator", request=user_request):
            initial_state: Dict[str, Any] = {
                "user_request": user_request,
                "customer_type": customer_type,
                # Inject dependencies so node functions can access them
                "_repository": self.repository,
                "_retriever": self.retriever,
                "_product_discovery": self.product_discovery,
                "_approval_queue": self.approval_queue,
            }

            final_state = self._compiled_graph.invoke(initial_state)

            # Return the quote if generation succeeded, otherwise an error dict
            if final_state.get("quote"):
                return final_state["quote"]

            return {
                "ok": False,
                "agent": final_state.get("error_agent", "LangGraphOrchestrator"),
                "message": final_state.get("error", "Unknown error during pipeline execution."),
            }
