"""
Guardrail agent checks before quote creation and before approval.
"""

from __future__ import annotations

from typing import Any, Dict, List


PROMPT_INJECTION_MARKERS = [
    "ignore previous instructions",
    "ignore all instructions",
    "bypass policy",
    "reveal system prompt",
    "developer message",
]

MAX_QUANTITY = 10000
MAX_AUTO_DISCOUNT = 0.20
MAX_AUTO_TOTAL = 250000.0


def guardrail_agent(
    request_text: str = "",
    items: List[Dict[str, Any]] | None = None,
    discount_pct: float = 0.0,
    known_products: List[str] | None = None,
    total: float = 0.0,
) -> Dict[str, Any]:
    """Validate quote safety, commercial policy, and output readiness."""
    items = items or []
    known_products = known_products or []
    issues = []

    lowered = request_text.lower()
    if any(marker in lowered for marker in PROMPT_INJECTION_MARKERS):
        issues.append("prompt_injection_detected")

    for item in items:
        qty = int(item.get("qty", 0))
        name = str(item.get("name", ""))
        if qty <= 0 or qty > MAX_QUANTITY:
            issues.append(f"invalid_quantity:{name}:{qty}")
        if known_products and name not in known_products:
            issues.append(f"missing_product:{name}")

    if discount_pct > MAX_AUTO_DISCOUNT:
        issues.append(f"unauthorized_discount:{discount_pct:.2f}")

    if total > MAX_AUTO_TOTAL:
        issues.append(f"financial_threshold_exceeded:{total:.2f}")

    required_item_fields = {"name", "qty", "unit_price", "total"}
    for item in items:
        missing = sorted(required_item_fields - set(item.keys()))
        if missing:
            issues.append(f"output_schema_missing:{','.join(missing)}")

    return {
        "approved": not issues,
        "issues": issues,
        "requires_human_approval": bool(issues) or total > 0,
    }
