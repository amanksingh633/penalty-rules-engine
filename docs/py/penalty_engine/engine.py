"""Evaluate rules against trips and produce findings (proposals, never charges)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from .models import Trip, compute_metrics, group_by_level, is_late, is_low_rated
from .rules import RuleSet


@dataclass(frozen=True)
class Finding:
    ticket_id: str
    rule_id: str
    level: str
    signal: str
    entity_id: str
    metric: str
    metric_value: float
    proposed_amount: float
    evidence_trip_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence_trip_ids"] = list(self.evidence_trip_ids)
        return d


def ticket_id_for(rule_id: str, entity_id: str, evidence: tuple[str, ...]) -> str:
    """Deterministic id, so re-running the same data never creates duplicate tickets."""
    digest = hashlib.sha1(f"{rule_id}|{entity_id}|{','.join(evidence)}".encode()).hexdigest()
    return f"PEN-{digest[:10].upper()}"


def _evidence(trips: list[Trip], signal: str, rules: RuleSet) -> tuple[str, ...]:
    if signal == "telematics":
        picked = [t for t in trips if is_late(t, rules.grace_minutes)]
    else:
        picked = [
            t for t in trips if t.conduct_flagged or is_low_rated(t, rules.low_rating_threshold)
        ]
    return tuple(sorted(t.trip_id for t in picked))


def evaluate(trips: list[Trip], ruleset: RuleSet) -> list[Finding]:
    findings = []
    for rule in ruleset.rules:
        for entity_id, group in group_by_level(trips, rule.level).items():
            if len(group) < rule.min_trips:
                continue
            metrics = compute_metrics(group, ruleset.grace_minutes, ruleset.low_rating_threshold)
            value = metrics[rule.metric]
            if not rule.triggered_by(value):
                continue
            evidence = _evidence(group, rule.signal, ruleset)
            findings.append(
                Finding(
                    ticket_id=ticket_id_for(rule.id, entity_id, evidence),
                    rule_id=rule.id,
                    level=rule.level,
                    signal=rule.signal,
                    entity_id=entity_id,
                    metric=rule.metric,
                    metric_value=value,
                    proposed_amount=rule.amount(metrics),
                    evidence_trip_ids=evidence,
                )
            )
    return sorted(findings, key=lambda f: (f.rule_id, f.entity_id))
