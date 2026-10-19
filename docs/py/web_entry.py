"""Browser entry point for the live demo (runs in Pyodide, also unit-tested with plain Python).

Every call returns one JSON string describing the current state. All penalty logic, the review
gate and the audit chain come from the real ``penalty_engine`` package.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from penalty_engine.engine import evaluate
from penalty_engine.models import load_trips
from penalty_engine.rules import load_rules
from penalty_engine.store import TicketStore, WorkflowError

_store: TicketStore | None = None


def _audit(store: TicketStore) -> list[dict]:
    if not store.audit_path.exists():
        return []
    lines = store.audit_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _state(error: str | None = None, info: str | None = None) -> str:
    if _store is None:
        return json.dumps({"error": error, "info": info, "tickets": [], "audit": []})
    ok, message = _store.verify_audit()
    return json.dumps(
        {
            "error": error,
            "info": info,
            "tickets": _store.list(),
            "audit": _audit(_store),
            "audit_ok": ok,
            "audit_message": message,
        }
    )


def start(trips_csv: str, rules_json: str) -> str:
    """Evaluate trips against rules in a fresh store and open a review ticket per finding."""
    global _store
    try:
        work = Path(tempfile.mkdtemp(prefix="penalty-"))
        (work / "trips.csv").write_text(trips_csv, encoding="utf-8")
        (work / "rules.json").write_text(rules_json, encoding="utf-8")
        findings = evaluate(load_trips(work / "trips.csv"), load_rules(work / "rules.json"))
    except (ValueError, KeyError, TypeError) as exc:  # bad CSV columns, bad JSON, bad rule
        return _state(error=f"Cannot evaluate: {exc}")
    _store = TicketStore(work / "store")
    created = _store.add_findings(findings)
    return _state(
        info=f"{len(findings)} findings, {len(created)} tickets opened (all PENDING_REVIEW)"
    )


def act(op: str, ticket_id: str, actor: str, note: str = "") -> str:
    """Confirm, reject or charge a ticket. Illegal moves come back as an error message."""
    if _store is None:
        return _state(error="Run an evaluation first.")
    try:
        if op == "confirm":
            _store.confirm(ticket_id, actor, note)
        elif op == "reject":
            _store.reject(ticket_id, actor, note)
        elif op == "charge":
            _store.charge(ticket_id, actor)
        else:
            return _state(error=f"Unknown action '{op}'")
    except WorkflowError as exc:
        return _state(error=str(exc))
    return _state(info=f"{ticket_id}: {op} recorded")


def tamper() -> str:
    """Rewrite the actor on the second audit record, as an attacker editing history would."""
    if _store is None:
        return _state(error="Run an evaluation first.")
    lines = _store.audit_path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        return _state(error="Nothing to tamper with yet.")
    record = json.loads(lines[1])
    record["actor"] = "someone-else"
    lines[1] = json.dumps(record)
    _store.audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _state(info="Audit record 2 was edited behind the system's back.")
