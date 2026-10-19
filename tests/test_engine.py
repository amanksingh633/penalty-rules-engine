import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from penalty_engine.cli import main
from penalty_engine.engine import evaluate
from penalty_engine.models import Trip, load_trips
from penalty_engine.rules import RuleError, load_rules
from penalty_engine.store import TicketStore, WorkflowError

DATA = Path(__file__).parent.parent / "sample_data"
T0 = datetime(2026, 10, 1, 9, 0)


def trip(tid, late=0, driver="D1", vehicle="V1", vendor="X", rating=5, flagged=False):
    return Trip(tid, driver, vehicle, vendor, T0, T0 + timedelta(minutes=late), rating, flagged)


def write_rules(tmp_path, rules, **top):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"rules": rules, **top}))
    return p


TRIP_LATE = {
    "id": "TRIP-LATE",
    "level": "trip",
    "signal": "telematics",
    "metric": "total_late_minutes",
    "op": ">=",
    "value": 30,
    "penalty": {"type": "per_unit", "metric": "total_late_minutes", "rate": 5, "cap": 200},
}


def test_trip_level_rule_fires_and_caps_amount(tmp_path):
    rs = load_rules(write_rules(tmp_path, [TRIP_LATE]))
    findings = evaluate([trip("a", late=45), trip("b", late=10), trip("c", late=100)], rs)
    by_entity = {f.entity_id: f for f in findings}
    assert set(by_entity) == {"a", "c"}
    assert by_entity["a"].proposed_amount == 200.0  # 45 * 5 = 225, capped at 200
    assert by_entity["c"].proposed_amount == 200.0


def test_grace_period_is_not_penalised(tmp_path):
    rule = {
        **TRIP_LATE,
        "metric": "late_trip_count",
        "value": 1,
        "penalty": {"type": "flat", "amount": 1},
    }
    rs = load_rules(write_rules(tmp_path, [rule], grace_minutes=10))
    assert evaluate([trip("a", late=10)], rs) == []
    assert len(evaluate([trip("a", late=11)], rs)) == 1


def test_driver_rule_needs_minimum_trips(tmp_path):
    rule = {
        "id": "DRV",
        "level": "driver",
        "signal": "telematics",
        "metric": "late_trip_count",
        "op": ">=",
        "value": 2,
        "min_trips": 4,
        "penalty": {"type": "flat", "amount": 100},
    }
    rs = load_rules(write_rules(tmp_path, [rule]))
    few = [trip("a", 20), trip("b", 20), trip("c")]
    assert evaluate(few, rs) == []  # only 3 trips: below min_trips
    enough = few + [trip("d")]
    (finding,) = evaluate(enough, rs)
    assert finding.evidence_trip_ids == ("a", "b")


def test_review_signal_uses_ratings_and_conduct_as_evidence(tmp_path):
    rule = {
        "id": "VEH",
        "level": "vehicle",
        "signal": "review",
        "metric": "avg_rating",
        "op": "<=",
        "value": 3.0,
        "penalty": {"type": "flat", "amount": 50},
    }
    rs = load_rules(write_rules(tmp_path, [rule]))
    trips = [trip("a", rating=1), trip("b", rating=5, flagged=True), trip("c", rating=3)]
    (finding,) = evaluate(trips, rs)
    assert finding.metric_value == 3.0
    assert finding.evidence_trip_ids == ("a", "b")


def test_missing_ratings_do_not_trigger_rating_rules(tmp_path):
    rule = {
        "id": "VEH",
        "level": "vehicle",
        "signal": "review",
        "metric": "avg_rating",
        "op": "<=",
        "value": 3.0,
        "penalty": {"type": "flat", "amount": 50},
    }
    rs = load_rules(write_rules(tmp_path, [rule]))
    assert evaluate([trip("a", rating=None)], rs) == []


@pytest.mark.parametrize(
    "mutation, message",
    [
        ({"level": "galaxy"}, "level"),
        ({"signal": "vibes"}, "signal"),
        ({"metric": "nope"}, "unknown metric"),
        ({"op": "~"}, "op"),
        ({"penalty": {"type": "flat"}}, "amount"),
        ({"penalty": {"type": "magic"}}, "penalty type"),
    ],
)
def test_invalid_rules_are_rejected(tmp_path, mutation, message):
    with pytest.raises(RuleError, match=message):
        load_rules(write_rules(tmp_path, [{**TRIP_LATE, **mutation}]))


def test_duplicate_rule_ids_are_rejected(tmp_path):
    with pytest.raises(RuleError, match="unique"):
        load_rules(write_rules(tmp_path, [TRIP_LATE, TRIP_LATE]))


def test_evaluation_is_idempotent(tmp_path):
    rs = load_rules(write_rules(tmp_path, [TRIP_LATE]))
    store = TicketStore(tmp_path / "s")
    findings = evaluate([trip("a", late=60)], rs)
    assert len(store.add_findings(findings)) == 1
    assert store.add_findings(findings) == []  # re-run creates nothing new
    assert len(store.list()) == 1


@pytest.fixture
def store_with_ticket(tmp_path):
    rs = load_rules(write_rules(tmp_path, [TRIP_LATE]))
    store = TicketStore(tmp_path / "s", clock=lambda: "2026-10-20T10:00:00+00:00")
    (tid,) = store.add_findings(evaluate([trip("a", late=60)], rs))
    return store, tid


def test_cannot_charge_without_confirmation(store_with_ticket):
    store, tid = store_with_ticket
    with pytest.raises(WorkflowError, match="needs CONFIRMED"):
        store.charge(tid, "billing-bot")


def test_confirm_requires_a_named_reviewer(store_with_ticket):
    store, tid = store_with_ticket
    with pytest.raises(WorkflowError, match="named reviewer"):
        store.confirm(tid, "  ")


def test_happy_path_and_no_double_charge(store_with_ticket):
    store, tid = store_with_ticket
    assert store.confirm(tid, "asha", "evidence checked")["status"] == "CONFIRMED"
    assert store.charge(tid, "billing-bot")["status"] == "CHARGED"
    with pytest.raises(WorkflowError):
        store.charge(tid, "billing-bot")


def test_rejected_ticket_can_never_be_charged(store_with_ticket):
    store, tid = store_with_ticket
    store.reject(tid, "asha", "driver was stuck behind an accident")
    with pytest.raises(WorkflowError):
        store.confirm(tid, "ravi")
    with pytest.raises(WorkflowError):
        store.charge(tid, "billing-bot")


def test_audit_log_records_every_step_and_detects_tampering(store_with_ticket):
    store, tid = store_with_ticket
    store.confirm(tid, "asha")
    store.charge(tid, "billing-bot")
    assert store.verify_audit() == (True, "audit log intact")

    lines = store.audit_path.read_text().splitlines()
    assert [json.loads(x)["action"] for x in lines] == ["CREATED", "CONFIRMED", "CHARGED"]

    tampered = json.loads(lines[1])
    tampered["actor"] = "someone-else"
    lines[1] = json.dumps(tampered)
    store.audit_path.write_text("\n".join(lines) + "\n")
    ok, message = store.verify_audit()
    assert not ok and "modified" in message

    store.audit_path.write_text("\n".join([lines[0], lines[2]]) + "\n")  # delete a record
    ok, message = store.verify_audit()
    assert not ok and "chain broken" in message


def test_sample_data_triggers_every_level():
    findings = evaluate(load_trips(DATA / "trips.csv"), load_rules(DATA / "rules.json"))
    assert {f.level for f in findings} == {"trip", "driver", "vehicle", "vendor"}
    assert any(f.entity_id == "D03" and f.level == "driver" for f in findings)
    assert any(f.entity_id == "V2" and f.level == "vendor" for f in findings)


def test_cli_end_to_end(tmp_path, capsys):
    store = str(tmp_path / "s")
    trips, rules = str(DATA / "trips.csv"), str(DATA / "rules.json")

    assert main(["--store", store, "evaluate", trips, rules]) == 0
    tid = next(iter(TicketStore(store).tickets))
    assert main(["--store", store, "charge", tid, "--actor", "bot"]) == 2  # blocked: not confirmed
    assert main(["--store", store, "confirm", tid, "--reviewer", "asha"]) == 0
    assert main(["--store", store, "charge", tid, "--actor", "bot"]) == 0
    assert main(["--store", store, "verify-audit"]) == 0
    out = capsys.readouterr().out
    assert "CHARGED" in out and "audit log intact" in out
