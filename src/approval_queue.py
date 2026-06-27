"""
Human-in-the-loop approval queue for generated quotes.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class ApprovalQueue:
    def __init__(self, queue_dir: Path, approved_dir: Path):
        self.queue_dir = queue_dir
        self.approved_dir = approved_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.approved_dir.mkdir(parents=True, exist_ok=True)

    def submit(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        quote["status"] = "pending_approval"
        quote["created_at"] = datetime.now(timezone.utc).isoformat()
        path = self.queue_dir / f"{quote['quote_id']}.json"
        path.write_text(json.dumps(quote, indent=2), encoding="utf-8")
        return {"status": "pending_approval", "approval_file": str(path), **quote}

    def list_pending(self) -> List[Dict[str, Any]]:
        quotes = []
        for path in sorted(self.queue_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            quotes.append(json.loads(path.read_text(encoding="utf-8")))
        return quotes

    def approve(self, quote_id: str, approver: str = "human") -> Dict[str, Any]:
        source = self.queue_dir / f"{quote_id}.json"
        if not source.exists():
            return {"ok": False, "message": f"Quote {quote_id} is not pending approval."}

        quote = json.loads(source.read_text(encoding="utf-8"))
        quote["status"] = "approved"
        quote["approved_by"] = approver
        quote["approved_at"] = datetime.now(timezone.utc).isoformat()
        target = self.approved_dir / f"{quote_id}.json"
        target.write_text(json.dumps(quote, indent=2), encoding="utf-8")
        source.unlink()
        return {"ok": True, "quote_id": quote_id, "approved_file": str(target)}

    def reject(self, quote_id: str, reason: str = "") -> Dict[str, Any]:
        source = self.queue_dir / f"{quote_id}.json"
        if not source.exists():
            return {"ok": False, "message": f"Quote {quote_id} is not pending approval."}

        rejected_dir = self.queue_dir / "rejected"
        rejected_dir.mkdir(exist_ok=True)
        quote = json.loads(source.read_text(encoding="utf-8"))
        quote["status"] = "rejected"
        quote["rejection_reason"] = reason
        quote["rejected_at"] = datetime.now(timezone.utc).isoformat()
        target = rejected_dir / f"{quote_id}.json"
        target.write_text(json.dumps(quote, indent=2), encoding="utf-8")
        source.unlink()
        return {"ok": True, "quote_id": quote_id, "rejected_file": str(target)}
