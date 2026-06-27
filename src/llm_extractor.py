"""
Structured LLM extraction for quote requests.

Replaces brittle regex parsing with Gemini's native structured JSON output
and Pydantic schema validation. Falls back to regex if the LLM call fails.
"""

from __future__ import annotations

import os
import re
import json
import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class QuoteRequest(BaseModel):
    """Validated extraction result from a user's quote request."""

    quantity: int = Field(ge=1, le=10000, description="Number of items requested")
    product: str = Field(min_length=1, description="Product name or description")
    customer: str = Field(min_length=1, description="Customer or company name")
    customer_type: Literal["regular", "preferred"] = Field(
        default="regular",
        description="Customer tier — 'preferred' if explicitly stated, else 'regular'",
    )


# ---------------------------------------------------------------------------
# Regex fallback (legacy pattern kept as safety net)
# ---------------------------------------------------------------------------

_FALLBACK_RE = re.compile(
    r"(?P<qty>\d+)\s+(?P<product>[A-Za-z ]+?)\s+for\s+(?P<customer>[A-Za-z0-9 &.\-]+?)(?:,|\.|$)",
    re.IGNORECASE,
)


def _regex_fallback(user_request: str) -> Optional[QuoteRequest]:
    """Attempt to parse the request with the legacy regex pattern."""
    match = _FALLBACK_RE.search(user_request)
    if not match:
        return None
    customer_type = "preferred" if "preferred" in user_request.lower() else "regular"
    try:
        return QuoteRequest(
            quantity=int(match.group("qty")),
            product=match.group("product").strip(),
            customer=match.group("customer").strip(),
            customer_type=customer_type,
        )
    except ValidationError:
        return None


# ---------------------------------------------------------------------------
# LLM Extractor
# ---------------------------------------------------------------------------

# The JSON schema that Gemini will be constrained to produce.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "quantity": {"type": "integer", "description": "Number of items"},
        "product": {"type": "string", "description": "Product name or description"},
        "customer": {"type": "string", "description": "Customer or company name"},
        "customer_type": {
            "type": "string",
            "enum": ["regular", "preferred"],
            "description": "Customer tier",
        },
    },
    "required": ["quantity", "product", "customer"],
}

_SYSTEM_PROMPT = """\
You are a quote request parser. Extract the following fields from the user's
request and return them as JSON:

- quantity: the number of items requested (integer, must be >= 1)
- product: the product name or description (string)
- customer: the customer or company name (string)
- customer_type: "preferred" if the user says preferred/VIP/premium customer,
  otherwise "regular"

Rules:
- If the request mentions a product in plural form (e.g. "chairs"), keep the
  plural as-is in the product field.
- Do NOT invent information that is not present in the request.
- If quantity is missing, set quantity to 0.
- If customer is missing, set customer to "".
"""


class LLMExtractor:
    """Extract structured quote fields using Gemini's native JSON output."""

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self._model_name = model_name
        self._client = None

    def _get_client(self):
        """Lazy-init the Gemini client."""
        if self._client is None:
            try:
                from google import genai

                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("AGENTX_GEMINI_API_KEY")
                if not api_key:
                    raise ValueError("No Gemini API key found in GOOGLE_API_KEY or AGENTX_GEMINI_API_KEY")
                self._client = genai.Client(api_key=api_key)
            except ImportError:
                raise ImportError("google-genai is required for LLM extraction: pip install google-genai")
        return self._client

    def extract(self, user_request: str) -> Optional[QuoteRequest]:
        """Extract structured fields from a free-text quote request.

        1. Calls Gemini with response_schema to get constrained JSON output.
        2. Validates the result with Pydantic.
        3. Falls back to regex if the LLM call fails.

        Returns:
            QuoteRequest if extraction succeeds, None if both LLM and regex fail.
        """
        # --- LLM extraction ---
        try:
            client = self._get_client()
            from google.genai import types as genai_types

            response = client.models.generate_content(
                model=self._model_name,
                contents=user_request,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                    temperature=0.0,
                ),
            )
            raw = response.text.strip()
            data = json.loads(raw)

            # Pydantic validation
            result = QuoteRequest(**data)

            # Reject if quantity is 0 (LLM was told to use 0 when missing)
            if result.quantity == 0:
                logger.warning("LLM extraction returned quantity=0, treating as missing")
                return None

            # Reject if customer is empty
            if not result.customer.strip():
                logger.warning("LLM extraction returned empty customer, treating as missing")
                return None

            logger.info(f"LLM extraction succeeded: {result.model_dump()}")
            return result

        except (ImportError, ValueError) as e:
            logger.warning(f"LLM extraction unavailable ({e}), falling back to regex")
        except ValidationError as e:
            logger.warning(f"LLM output failed Pydantic validation: {e}")
        except Exception as e:
            logger.warning(f"LLM extraction failed ({type(e).__name__}: {e}), falling back to regex")

        # --- Regex fallback ---
        fallback = _regex_fallback(user_request)
        if fallback:
            logger.info(f"Regex fallback succeeded: {fallback.model_dump()}")
        else:
            logger.warning(f"Both LLM and regex extraction failed for: {user_request!r}")
        return fallback


# ---------------------------------------------------------------------------
# Module-level convenience instance
# ---------------------------------------------------------------------------

_default_extractor = LLMExtractor()


def extract_quote_request(user_request: str) -> Optional[QuoteRequest]:
    """Module-level convenience function wrapping the default extractor."""
    return _default_extractor.extract(user_request)
