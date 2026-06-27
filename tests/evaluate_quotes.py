"""
Comprehensive evaluation framework for the multi-agent quoting pipeline.

Computes 12 metrics across 4 categories:

A. Core Pipeline Metrics
   - Task Success Rate
   - End-to-End Quote Accuracy
   - Approval Escalation Rate
   - Average Latency

B. Product Matching Metrics
   - Product Match Accuracy
   - Hallucination Rate

C. Retrieval Quality Metrics (RAG product discovery)
   - Precision@K
   - Recall@K
   - MRR (Mean Reciprocal Rank)
   - Retrieval Precision

D. Agent Behavior Metrics
   - Tool Call Accuracy
   - Parsing Accuracy
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src/ to path for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

try:
    from langgraph_orchestrator import LangGraphQuoteOrchestrator as Orchestrator
except ImportError:
    from multi_agent_quote import SupervisorAgent as Orchestrator  # type: ignore[assignment]

try:
    from product_discovery import ProductDiscovery
except ImportError:
    ProductDiscovery = None  # type: ignore[misc,assignment]

TESTS_DIR = Path(__file__).resolve().parent
ROOT = _PROJECT_ROOT
DATA_DIR = ROOT / "data"
APPROVAL_DIR = ROOT / "approval_queue"
OUT_DIR = ROOT / "quotes"
TELEMETRY = DATA_DIR / "evaluation_observability.jsonl"
PRODUCTS_CSV = DATA_DIR / "products.csv"
VECTOR_STORE = DATA_DIR / "vector_store"

KNOWN_PRODUCTS = {"Office Chair", "Conference Table", "Developer Desk", "Visitor Stool"}


# ============================================================================
# Per-case evaluation
# ============================================================================


def evaluate_case(
    agent: Any,
    case: Dict[str, Any],
    discovery: Any | None = None,
) -> Dict[str, Any]:
    """Run a single test case through the pipeline and compute per-case metrics."""

    case_id = case["id"]
    request = case["request"]
    expects_error = case.get("expected_error", False)

    # ── Run the pipeline ────────────────────────────────────────────────
    start = time.perf_counter()
    try:
        result = agent.run(
            request,
            customer_type="preferred" if "preferred" in request.lower() else "regular",
        )
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "agent": "EXCEPTION"}
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    # ── Task success ────────────────────────────────────────────────────
    is_success = bool(result.get("status") == "pending_approval") if not expects_error else bool(result.get("ok") is False or result.get("error") or result.get("message"))

    # ── Parsing accuracy ────────────────────────────────────────────────
    expected_parsing = case.get("expected_parsing_fields")
    parsing_correct = None  # None = not evaluated
    if expected_parsing is not None:
        # For successful parses, check the fields propagated into the result
        parsed_customer = result.get("customer", "")
        parsed_qty = 0
        if result.get("items"):
            parsed_qty = result["items"][0].get("qty", 0)
        parsed_product = ""
        if result.get("items"):
            parsed_product = result["items"][0].get("name", "")

        parsing_correct = (
            parsed_customer.lower().strip() == expected_parsing.get("customer", "").lower().strip()
            and parsed_qty == expected_parsing.get("quantity", 0)
        ) if parsed_customer and parsed_qty else False
    elif case.get("expected_parse_failure"):
        # We expected parsing to fail
        parsing_correct = result.get("ok") is False

    # ── Product match accuracy ──────────────────────────────────────────
    expected_product = case.get("expected_product")
    product_match = None
    if expected_product:
        actual_products = [item.get("name") for item in result.get("items", [])]
        product_match = expected_product in actual_products

    # ── Hallucination ───────────────────────────────────────────────────
    hallucination = False
    if result.get("items"):
        hallucination = any(
            item.get("name") not in KNOWN_PRODUCTS
            for item in result["items"]
        )

    # ── End-to-end quote accuracy (all fields correct) ──────────────────
    e2e_correct = True
    if not expects_error:
        checks = []
        if expected_product:
            checks.append(product_match is True)
        if "expected_customer" in case:
            checks.append(result.get("customer", "").lower().strip() == case["expected_customer"].lower().strip())
        if "expected_qty" in case and result.get("items"):
            checks.append(result["items"][0].get("qty") == case["expected_qty"])
        if "expected_status" in case:
            checks.append(result.get("status") == case["expected_status"])
        e2e_correct = all(checks) if checks else False
    else:
        e2e_correct = is_success  # for error cases, "correct" means it correctly errored

    # ── Approval escalation ─────────────────────────────────────────────
    guardrails = result.get("guardrails", {})
    escalated = guardrails.get("requires_human_approval", False)
    guardrail_issues = guardrails.get("issues", [])

    expected_issue = case.get("expected_guardrail_issue")
    guardrail_ok = True
    if expected_issue:
        guardrail_ok = expected_issue in guardrail_issues

    # ── Tool call accuracy ──────────────────────────────────────────────
    expected_sequence = case.get("expected_tool_sequence", [])
    actual_agents = _infer_agent_sequence(result, case)
    tool_call_ok = actual_agents == expected_sequence

    # ── Retrieval quality (Precision@K, Recall@K, MRR) ──────────────────
    retrieval_metrics = _compute_retrieval_metrics(case, result, discovery)

    # ── Discovery match type ────────────────────────────────────────────
    expected_match_type = case.get("expected_match_type")
    actual_match_type = result.get("match_type") or (
        "exact" if not result.get("requested_product") and not expects_error and is_success
        else result.get("discovery_match_type")
    )
    match_type_ok = expected_match_type == actual_match_type if expected_match_type else None

    return {
        "id": case_id,
        "latency_ms": latency_ms,
        # Core pipeline
        "task_success": is_success,
        "e2e_correct": e2e_correct,
        "escalated": escalated,
        # Product matching
        "product_match": product_match,
        "hallucination": hallucination,
        # Retrieval
        **retrieval_metrics,
        # Agent behavior
        "tool_call_ok": tool_call_ok,
        "parsing_correct": parsing_correct,
        # Extra details
        "guardrail_ok": guardrail_ok,
        "match_type_ok": match_type_ok,
        "result_summary": {
            "ok": result.get("ok"),
            "agent": result.get("agent"),
            "status": result.get("status"),
            "message": result.get("message"),
            "quote_id": result.get("quote_id"),
            "match_type": actual_match_type,
        },
    }


# ============================================================================
# Retrieval metrics helpers
# ============================================================================


def _compute_retrieval_metrics(
    case: Dict[str, Any],
    result: Dict[str, Any],
    discovery: Any | None,
) -> Dict[str, Any]:
    """Compute Precision@K, Recall@K, MRR for a single case."""
    expected_candidates = case.get("expected_retrieval_candidates")
    if not expected_candidates or discovery is None:
        return {
            "precision_at_k": None,
            "recall_at_k": None,
            "mrr": None,
            "retrieval_precision": None,
        }

    # Get actual retrieval results from product discovery
    query = case.get("expected_parsing_fields", {})
    query_text = query.get("product", "") if query else ""
    if not query_text:
        return {
            "precision_at_k": None,
            "recall_at_k": None,
            "mrr": None,
            "retrieval_precision": None,
        }

    try:
        retrieved = discovery.find_similar(query_text, top_k=5)
    except Exception:
        return {
            "precision_at_k": None,
            "recall_at_k": None,
            "mrr": None,
            "retrieval_precision": None,
        }

    retrieved_names = [r.get("product_name", "") for r in retrieved]
    expected_set = set(expected_candidates)
    k = len(retrieved_names) or 1

    # Precision@K = |relevant ∩ retrieved@k| / k
    relevant_in_top_k = sum(1 for name in retrieved_names if name in expected_set)
    precision_at_k = round(relevant_in_top_k / k, 4)

    # Recall@K = |relevant ∩ retrieved@k| / |relevant|
    total_relevant = len(expected_set) or 1
    recall_at_k = round(relevant_in_top_k / total_relevant, 4)

    # MRR = 1 / rank_of_first_relevant
    mrr = 0.0
    for rank, name in enumerate(retrieved_names, 1):
        if name in expected_set:
            mrr = round(1.0 / rank, 4)
            break

    # Retrieval Precision = was the top-1 result correct?
    retrieval_precision = 1.0 if retrieved_names and retrieved_names[0] in expected_set else 0.0

    return {
        "precision_at_k": precision_at_k,
        "recall_at_k": recall_at_k,
        "mrr": mrr,
        "retrieval_precision": retrieval_precision,
    }


def _infer_agent_sequence(result: Dict[str, Any], case: Dict[str, Any]) -> List[str]:
    """Infer which agents were invoked based on result shape."""
    agents: List[str] = []

    # RetrieverAgent always runs first (parsing)
    agents.append("RetrieverAgent")

    # If we got past parsing...
    if result.get("ok") is False and result.get("agent") == "RetrieverAgent":
        return agents

    # ProductDiscoveryAgent
    if case.get("expected_discovery_used") is not None or result.get("requested_product") or result.get("discovery_match_type"):
        agents.append("ProductDiscoveryAgent")
        # If discovery failed
        if result.get("ok") is False and result.get("agent") == "ProductDiscoveryAgent":
            return agents
        if result.get("match_type") in ("no_match", "ask_user"):
            return agents

    # PricingAgent
    if result.get("items") or (result.get("ok") is False and result.get("agent") == "PricingAgent"):
        agents.append("PricingAgent")
        if result.get("ok") is False and result.get("agent") == "PricingAgent":
            return agents

    # QuoteGeneratorAgent (we got a quote)
    if result.get("quote_id"):
        agents.append("QuoteGeneratorAgent")

    return agents


# ============================================================================
# Aggregate metrics
# ============================================================================


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate metrics across all test cases."""
    total = len(results) or 1

    # Helper to average non-None values
    def _avg(key: str) -> Optional[float]:
        vals = [r[key] for r in results if r[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    def _rate(key: str) -> float:
        vals = [r[key] for r in results if r[key] is not None]
        return round(sum(1 for v in vals if v) / (len(vals) or 1), 4)

    report = {
        "total_cases": total,

        # ── Category A: Core Pipeline Metrics ──────────────────────────
        "core_pipeline": {
            "task_success_rate": round(
                sum(1 for r in results if r["task_success"]) / total, 4
            ),
            "e2e_quote_accuracy": round(
                sum(1 for r in results if r["e2e_correct"]) / total, 4
            ),
            "approval_escalation_rate": round(
                sum(1 for r in results if r["escalated"]) / total, 4
            ),
            "avg_latency_ms": round(
                sum(r["latency_ms"] for r in results) / total, 2
            ),
        },

        # ── Category B: Product Matching Metrics ───────────────────────
        "product_matching": {
            "product_match_accuracy": _rate("product_match"),
            "hallucination_rate": round(
                sum(1 for r in results if r["hallucination"]) / total, 4
            ),
        },

        # ── Category C: Retrieval Quality Metrics ──────────────────────
        "retrieval_quality": {
            "precision_at_k": _avg("precision_at_k"),
            "recall_at_k": _avg("recall_at_k"),
            "mrr": _avg("mrr"),
            "retrieval_precision": _avg("retrieval_precision"),
        },

        # ── Category D: Agent Behavior Metrics ─────────────────────────
        "agent_behavior": {
            "tool_call_accuracy": round(
                sum(1 for r in results if r["tool_call_ok"]) / total, 4
            ),
            "parsing_accuracy": _rate("parsing_correct"),
        },

        # ── Per-case details ───────────────────────────────────────────
        "per_case": results,
    }

    return report


# ============================================================================
# Pretty-print report
# ============================================================================


def print_report(report: Dict[str, Any]) -> None:
    """Print a human-readable evaluation report to stdout."""
    print("\n" + "=" * 72)
    print("  SMART QUOTING AGENT — EVALUATION REPORT")
    print("=" * 72)

    print(f"\n  Total test cases: {report['total_cases']}")

    core = report["core_pipeline"]
    print("\n  ── A. Core Pipeline Metrics ──────────────────────────────")
    print(f"     Task Success Rate ........... {core['task_success_rate']:.2%}")
    print(f"     E2E Quote Accuracy .......... {core['e2e_quote_accuracy']:.2%}")
    print(f"     Approval Escalation Rate .... {core['approval_escalation_rate']:.2%}")
    print(f"     Avg Latency ................. {core['avg_latency_ms']:.1f} ms")

    pm = report["product_matching"]
    print("\n  ── B. Product Matching Metrics ───────────────────────────")
    print(f"     Product Match Accuracy ...... {pm['product_match_accuracy']:.2%}")
    print(f"     Hallucination Rate .......... {pm['hallucination_rate']:.2%}")

    rq = report["retrieval_quality"]
    print("\n  ── C. Retrieval Quality Metrics (RAG) ────────────────────")
    print(f"     Precision@K ................. {rq['precision_at_k']:.4f}" if rq["precision_at_k"] is not None else "     Precision@K ................. N/A")
    print(f"     Recall@K .................... {rq['recall_at_k']:.4f}" if rq["recall_at_k"] is not None else "     Recall@K .................... N/A")
    print(f"     MRR ......................... {rq['mrr']:.4f}" if rq["mrr"] is not None else "     MRR ......................... N/A")
    print(f"     Retrieval Precision ......... {rq['retrieval_precision']:.4f}" if rq["retrieval_precision"] is not None else "     Retrieval Precision ......... N/A")

    ab = report["agent_behavior"]
    print("\n  ── D. Agent Behavior Metrics ─────────────────────────────")
    print(f"     Tool Call Accuracy .......... {ab['tool_call_accuracy']:.2%}")
    print(f"     Parsing Accuracy ............ {ab['parsing_accuracy']:.2%}")

    print("\n  ── Per-Case Breakdown ────────────────────────────────────")
    for r in report["per_case"]:
        status = "✅" if r["task_success"] else "❌"
        e2e = "✅" if r["e2e_correct"] else "❌"
        pm_icon = "✅" if r.get("product_match") else ("➖" if r["product_match"] is None else "❌")
        hall = "⚠️" if r["hallucination"] else "✅"
        tc = "✅" if r["tool_call_ok"] else "❌"
        print(f"     {r['id']:<32s}  success={status}  e2e={e2e}  product={pm_icon}  halluc={hall}  tools={tc}  {r['latency_ms']:.0f}ms")

    print("\n" + "=" * 72)


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    cases = json.loads((TESTS_DIR / "test_cases.json").read_text(encoding="utf-8"))

    agent = Orchestrator(DATA_DIR, APPROVAL_DIR, OUT_DIR, TELEMETRY)

    # Initialize product discovery for retrieval metrics
    discovery = None
    if ProductDiscovery is not None and PRODUCTS_CSV.exists():
        try:
            discovery = ProductDiscovery(PRODUCTS_CSV, VECTOR_STORE)
        except Exception:
            pass

    results = [evaluate_case(agent, case, discovery) for case in cases]
    report = summarize(results)

    # Save JSON report
    report_path = DATA_DIR / "evaluation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Print human-readable report
    print_report(report)

    print(f"\n  📄 Full report saved to: {report_path}")


if __name__ == "__main__":
    main()
