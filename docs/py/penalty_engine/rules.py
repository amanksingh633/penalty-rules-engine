"""Rule definitions loaded from JSON, validated up front so bad config fails fast."""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from pathlib import Path

from .models import LEVELS

OPS = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
}
SIGNALS = ("telematics", "review")
METRICS = (
    "trip_count",
    "late_trip_count",
    "late_rate",
    "total_late_minutes",
    "low_rating_count",
    "avg_rating",
    "conduct_flag_count",
)


class RuleError(ValueError):
    """Raised for an invalid rule file."""


@dataclass(frozen=True)
class Rule:
    id: str
    level: str
    signal: str  # telematics -> lateness evidence, review -> conduct evidence
    metric: str
    op: str
    value: float
    penalty: dict
    min_trips: int = 1

    def triggered_by(self, metric_value: float | None) -> bool:
        return metric_value is not None and OPS[self.op](metric_value, self.value)

    def amount(self, metrics: dict[str, float | None]) -> float:
        p = self.penalty
        if p["type"] == "flat":
            return float(p["amount"])
        raw = float(metrics[p["metric"]] or 0) * float(p["rate"])
        return round(min(raw, float(p["cap"])) if "cap" in p else raw, 2)


@dataclass(frozen=True)
class RuleSet:
    rules: list[Rule]
    grace_minutes: float = 5
    low_rating_threshold: int = 2


def _validate(raw: dict) -> Rule:
    required = {"id", "level", "signal", "metric", "op", "value", "penalty"}
    missing = required - raw.keys()
    if missing:
        raise RuleError(f"rule {raw.get('id', '?')}: missing {sorted(missing)}")
    rid = raw["id"]
    if raw["level"] not in LEVELS:
        raise RuleError(f"rule {rid}: level must be one of {LEVELS}")
    if raw["signal"] not in SIGNALS:
        raise RuleError(f"rule {rid}: signal must be one of {SIGNALS}")
    if raw["metric"] not in METRICS:
        raise RuleError(f"rule {rid}: unknown metric '{raw['metric']}'")
    if raw["op"] not in OPS:
        raise RuleError(f"rule {rid}: op must be one of {list(OPS)}")
    pen = raw["penalty"]
    if pen.get("type") == "flat":
        if "amount" not in pen:
            raise RuleError(f"rule {rid}: flat penalty needs 'amount'")
    elif pen.get("type") == "per_unit":
        if not {"metric", "rate"} <= pen.keys() or pen["metric"] not in METRICS:
            raise RuleError(f"rule {rid}: per_unit penalty needs a valid 'metric' and 'rate'")
    else:
        raise RuleError(f"rule {rid}: penalty type must be 'flat' or 'per_unit'")
    return Rule(
        id=rid,
        level=raw["level"],
        signal=raw["signal"],
        metric=raw["metric"],
        op=raw["op"],
        value=float(raw["value"]),
        penalty=pen,
        min_trips=int(raw.get("min_trips", 1)),
    )


def load_rules(path: str | Path) -> RuleSet:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = [_validate(r) for r in data.get("rules", [])]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise RuleError("rule ids must be unique")
    return RuleSet(
        rules=rules,
        grace_minutes=data.get("grace_minutes", 5),
        low_rating_threshold=data.get("low_rating_threshold", 2),
    )
