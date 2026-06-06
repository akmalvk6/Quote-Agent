"""
Evaluation runner for the multi-agent quoting pipeline.

It is intentionally dependency-light. You can later replace or supplement these
checks with LangSmith, DeepEval, or Ragas, while keeping test_cases.json as the
shared test corpus.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from multi_agent_quote import SupervisorAgent


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
APPROVAL_DIR = ROOT / "approval_queue"
OUT_DIR = ROOT / "quotes"
TELEMETRY = DATA_DIR / "evaluation_observability.jsonl"


def evaluate_case(agent: SupervisorAgent, case: Dict[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    result = agent.run(
        case["request"],
        customer_type="preferred" if "preferred" in case["request"].lower() else "regular",
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    accuracy_checks = []
    if "expected_product" in case:
        products = [item.get("name") for item in result.get("items", [])]
        accuracy_checks.append(case["expected_product"] in products)
    if "expected_customer" in case:
        accuracy_checks.append(result.get("customer") == case["expected_customer"])
    if "expected_status" in case:
        accuracy_checks.append(result.get("status") == case["expected_status"])
    if "expected_error" in case:
        accuracy_checks.append(case["expected_error"] in result.get("message", ""))

    expected_issue = case.get("expected_guardrail_issue")
    if expected_issue:
        issues = result.get("guardrails", {}).get("issues", [])
        accuracy_checks.append(expected_issue in issues)

    hallucination = False
    if result.get("items"):
        known_products = {"Office Chair", "Conference Table", "Developer Desk", "Visitor Stool"}
        hallucination = any(item.get("name") not in known_products for item in result["items"])

    actual_agents = []
    if result.get("agent"):
        actual_agents.append(result["agent"])
    if result.get("items"):
        actual_agents = ["RetrieverAgent", "PricingAgent", "QuoteGeneratorAgent"]
    elif result.get("agent") == "PricingAgent":
        actual_agents = ["RetrieverAgent", "PricingAgent"]
    elif result.get("agent") == "RetrieverAgent":
        actual_agents = ["RetrieverAgent"]

    expected_sequence = case.get("expected_tool_sequence", [])
    tool_selection_ok = actual_agents == expected_sequence

    return {
        "id": case["id"],
        "latency_ms": latency_ms,
        "accuracy_ok": all(accuracy_checks) if accuracy_checks else True,
        "hallucination": hallucination,
        "tool_selection_ok": tool_selection_ok,
        "result_summary": {
            "ok": result.get("ok"),
            "agent": result.get("agent"),
            "status": result.get("status"),
            "message": result.get("message"),
            "quote_id": result.get("quote_id"),
        },
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results) or 1
    return {
        "cases": len(results),
        "accuracy": round(sum(r["accuracy_ok"] for r in results) / total, 3),
        "hallucination_rate": round(sum(r["hallucination"] for r in results) / total, 3),
        "tool_selection_accuracy": round(sum(r["tool_selection_ok"] for r in results) / total, 3),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / total, 2),
        "results": results,
    }


def main() -> None:
    cases = json.loads((ROOT / "test_cases.json").read_text(encoding="utf-8"))
    agent = SupervisorAgent(DATA_DIR, APPROVAL_DIR, OUT_DIR, TELEMETRY)
    results = [evaluate_case(agent, case) for case in cases]
    report = summarize(results)
    report_path = DATA_DIR / "evaluation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
