"""The GitHub Pages demo ships copies of the package; keep them honest."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"


def _load_web_entry():
    """Load docs/py/web_entry.py by path so the shipped package copy never shadows src/."""
    spec = importlib.util.spec_from_file_location("web_entry", DOCS / "py" / "web_entry.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


web_entry = _load_web_entry()

TRIPS = (DOCS / "sample" / "trips.csv").read_text(encoding="utf-8")
RULES = (DOCS / "sample" / "rules.json").read_text(encoding="utf-8")


def test_demo_package_matches_source():
    for name in ("__init__.py", "models.py", "rules.py", "engine.py", "store.py"):
        shipped = (DOCS / "py" / "penalty_engine" / name).read_text(encoding="utf-8")
        source = (ROOT / "src" / "penalty_engine" / name).read_text(encoding="utf-8")
        assert shipped == source, (
            f"docs/py/penalty_engine/{name} is stale: run scripts/sync_demo.py"
        )


def test_demo_sample_data_matches_source():
    for name in ("trips.csv", "rules.json"):
        shipped = (DOCS / "sample" / name).read_bytes()
        source = (ROOT / "sample_data" / name).read_bytes()
        assert shipped == source, f"docs/sample/{name} is stale: run scripts/sync_demo.py"


def _call(fn, *args):
    return json.loads(fn(*args))


def test_start_opens_pending_tickets_for_every_finding():
    state = _call(web_entry.start, TRIPS, RULES)
    assert state["error"] is None
    assert len(state["tickets"]) == 14
    assert {t["status"] for t in state["tickets"]} == {"PENDING_REVIEW"}
    assert {t["level"] for t in state["tickets"]} == {"trip", "driver", "vehicle", "vendor"}
    assert state["audit_ok"] is True


def test_review_gate_blocks_charging_until_confirmed():
    tid = _call(web_entry.start, TRIPS, RULES)["tickets"][0]["ticket_id"]

    blocked = _call(web_entry.act, "charge", tid, "billing-bot")
    assert "needs CONFIRMED" in blocked["error"]

    assert "named reviewer" in _call(web_entry.act, "confirm", tid, "  ")["error"]

    confirmed = _call(web_entry.act, "confirm", tid, "asha", "checked")
    status = {t["ticket_id"]: t["status"] for t in confirmed["tickets"]}
    assert status[tid] == "CONFIRMED"

    charged = _call(web_entry.act, "charge", tid, "billing-bot")
    assert {t["ticket_id"]: t["status"] for t in charged["tickets"]}[tid] == "CHARGED"
    assert [r["action"] for r in charged["audit"][-2:]] == ["CONFIRMED", "CHARGED"]
    assert charged["audit_ok"] is True


def test_tampering_with_the_audit_log_is_detected():
    tid = _call(web_entry.start, TRIPS, RULES)["tickets"][0]["ticket_id"]
    _call(web_entry.act, "confirm", tid, "asha")
    tampered = _call(web_entry.tamper)
    assert tampered["audit_ok"] is False
    assert "modified" in tampered["audit_message"]


def test_bad_input_returns_an_error_not_an_exception():
    assert "Cannot evaluate" in _call(web_entry.start, TRIPS, "{not json")["error"]
    assert "Cannot evaluate" in _call(web_entry.start, "a,b\n1,2\n", RULES)["error"]
    bad_rule = json.dumps({"rules": [{"id": "x", "level": "galaxy"}]})
    assert "Cannot evaluate" in _call(web_entry.start, TRIPS, bad_rule)["error"]


def test_precomputed_snapshot_matches_a_live_run():
    """The page shows this file before Python loads; its tickets must match a live run."""
    snapshot = json.loads((DOCS / "sample" / "precomputed.json").read_text(encoding="utf-8"))
    live = _call(web_entry.start, TRIPS, RULES)
    assert snapshot["tickets"] == live["tickets"], (
        "docs/sample/precomputed.json is stale: run scripts/sync_demo.py"
    )
    assert [r["action"] for r in snapshot["audit"]] == [r["action"] for r in live["audit"]]
    assert snapshot["audit_ok"] is True
