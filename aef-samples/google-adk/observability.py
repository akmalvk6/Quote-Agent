"""
Lightweight observability for agent latency, tool calls, token usage, and failures.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator


class Observability:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    @contextmanager
    def span(self, name: str, **payload: Any) -> Iterator[None]:
        start = time.perf_counter()
        self.emit(f"{name}.start", payload)
        try:
            yield
        except Exception as exc:
            self.emit(
                f"{name}.failure",
                {**payload, "latency_ms": round((time.perf_counter() - start) * 1000, 2), "error": str(exc)},
            )
            raise
        else:
            self.emit(
                f"{name}.success",
                {**payload, "latency_ms": round((time.perf_counter() - start) * 1000, 2)},
            )
