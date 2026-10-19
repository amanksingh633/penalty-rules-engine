"""Ticket workflow and audit trail.

Findings become review tickets. A ticket can only be charged after a named reviewer confirms it.
Every state change is appended to a hash-chained audit log, so editing or deleting history is
detectable by ``verify_audit``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .engine import Finding

PENDING, CONFIRMED, REJECTED, CHARGED = "PENDING_REVIEW", "CONFIRMED", "REJECTED", "CHARGED"
_ALLOWED = {
    "confirm": (PENDING, CONFIRMED),
    "reject": (PENDING, REJECTED),
    "charge": (CONFIRMED, CHARGED),
}


class WorkflowError(Exception):
    """Raised for an illegal state transition or missing reviewer."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TicketStore:
    def __init__(self, directory: str | Path, clock: Callable[[], str] = _utcnow):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tickets_path = self.dir / "tickets.json"
        self.audit_path = self.dir / "audit.jsonl"
        self._clock = clock
        self.tickets: dict[str, dict] = (
            json.loads(self.tickets_path.read_text(encoding="utf-8"))
            if self.tickets_path.exists()
            else {}
        )

    # -- persistence -------------------------------------------------------------------------
    def _save(self) -> None:
        self.tickets_path.write_text(json.dumps(self.tickets, indent=2, sort_keys=True), "utf-8")

    def _audit_records(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def _append_audit(self, ticket_id: str, action: str, actor: str, detail: str = "") -> None:
        records = self._audit_records()
        prev = records[-1]["hash"] if records else "0" * 64
        body = {
            "seq": len(records) + 1,
            "ts": self._clock(),
            "ticket_id": ticket_id,
            "action": action,
            "actor": actor,
            "detail": detail,
            "prev_hash": prev,
        }
        body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(body) + "\n")

    # -- workflow ----------------------------------------------------------------------------
    def add_findings(self, findings: list[Finding]) -> list[str]:
        """Create tickets for new findings only. Returns the ids that were created."""
        created = []
        for f in findings:
            if f.ticket_id in self.tickets:
                continue
            self.tickets[f.ticket_id] = {**f.to_dict(), "status": PENDING, "reviewer": None}
            self._append_audit(f.ticket_id, "CREATED", "system", f"rule {f.rule_id}")
            created.append(f.ticket_id)
        self._save()
        return created

    def _transition(self, action: str, ticket_id: str, actor: str, note: str = "") -> dict:
        if not actor.strip():
            raise WorkflowError(f"'{action}' requires a named reviewer")
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            raise WorkflowError(f"unknown ticket {ticket_id}")
        required, new_status = _ALLOWED[action]
        if ticket["status"] != required:
            raise WorkflowError(
                f"cannot {action} {ticket_id}: status is {ticket['status']}, needs {required}"
            )
        ticket["status"] = new_status
        if action != "charge":
            ticket["reviewer"] = actor
        self._append_audit(ticket_id, new_status, actor, note)
        self._save()
        return ticket

    def confirm(self, ticket_id: str, reviewer: str, note: str = "") -> dict:
        return self._transition("confirm", ticket_id, reviewer, note)

    def reject(self, ticket_id: str, reviewer: str, note: str = "") -> dict:
        return self._transition("reject", ticket_id, reviewer, note)

    def charge(self, ticket_id: str, actor: str) -> dict:
        """Mark a confirmed ticket as charged. (Records intent only; no payment is made.)"""
        return self._transition("charge", ticket_id, actor)

    def list(self, status: str | None = None) -> list[dict]:
        rows = sorted(self.tickets.values(), key=lambda t: t["ticket_id"])
        return [t for t in rows if status is None or t["status"] == status]

    def verify_audit(self) -> tuple[bool, str]:
        """Recompute the hash chain. Returns (ok, message)."""
        prev = "0" * 64
        for rec in self._audit_records():
            claimed = rec["hash"]
            body = {k: v for k, v in rec.items() if k != "hash"}
            if body["prev_hash"] != prev:
                return False, f"chain broken at seq {rec['seq']}"
            expected = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            if expected != claimed:
                return False, f"record {rec['seq']} was modified"
            prev = claimed
        return True, "audit log intact"
