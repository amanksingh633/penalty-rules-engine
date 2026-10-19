"""Trip records and the metrics computed from them."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LEVELS = ("trip", "driver", "vehicle", "vendor")
_LEVEL_ATTR = {
    "trip": "trip_id",
    "driver": "driver_id",
    "vehicle": "vehicle_id",
    "vendor": "vendor_id",
}


@dataclass(frozen=True)
class Trip:
    trip_id: str
    driver_id: str
    vehicle_id: str
    vendor_id: str
    scheduled_arrival: datetime
    actual_arrival: datetime  # from telematics
    rider_rating: int | None  # from rider reviews, 1-5, may be missing
    conduct_flagged: bool  # rider flagged conduct in their review

    @property
    def late_minutes(self) -> float:
        delta = (self.actual_arrival - self.scheduled_arrival).total_seconds() / 60
        return round(max(0.0, delta), 1)


def load_trips(path: str | Path) -> list[Trip]:
    trips = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rating = row["rider_rating"].strip()
            trips.append(
                Trip(
                    trip_id=row["trip_id"],
                    driver_id=row["driver_id"],
                    vehicle_id=row["vehicle_id"],
                    vendor_id=row["vendor_id"],
                    scheduled_arrival=datetime.fromisoformat(row["scheduled_arrival"]),
                    actual_arrival=datetime.fromisoformat(row["actual_arrival"]),
                    rider_rating=int(rating) if rating else None,
                    conduct_flagged=row["conduct_flagged"].strip().lower() in {"1", "true", "yes"},
                )
            )
    return trips


def group_by_level(trips: list[Trip], level: str) -> dict[str, list[Trip]]:
    attr = _LEVEL_ATTR[level]
    groups: dict[str, list[Trip]] = {}
    for t in trips:
        groups.setdefault(getattr(t, attr), []).append(t)
    return groups


def is_late(trip: Trip, grace_minutes: float) -> bool:
    return trip.late_minutes > grace_minutes


def is_low_rated(trip: Trip, low_rating_threshold: int) -> bool:
    return trip.rider_rating is not None and trip.rider_rating <= low_rating_threshold


def compute_metrics(
    trips: list[Trip], grace_minutes: float, low_rating_threshold: int
) -> dict[str, float | None]:
    """Metrics for one entity (a trip, driver, vehicle, or vendor) over the supplied trips."""
    ratings = [t.rider_rating for t in trips if t.rider_rating is not None]
    late = [t for t in trips if is_late(t, grace_minutes)]
    return {
        "trip_count": len(trips),
        "late_trip_count": len(late),
        "late_rate": len(late) / len(trips),
        "total_late_minutes": round(sum(t.late_minutes for t in late), 1),
        "low_rating_count": sum(is_low_rated(t, low_rating_threshold) for t in trips),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "conduct_flag_count": sum(t.conduct_flagged for t in trips),
    }
