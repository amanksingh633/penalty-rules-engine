"""Generate a small synthetic trips file. All data is random; none of it is real.

Run:  python sample_data/generate.py
Plants a few clear patterns (a chronically late driver, a poorly rated vehicle, a late-prone
vendor, and one trip with a conduct flag) so every rule level has something to find.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
FIELDS = [
    "trip_id",
    "driver_id",
    "vehicle_id",
    "vendor_id",
    "scheduled_arrival",
    "actual_arrival",
    "rider_rating",
    "conduct_flagged",
]


def build(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    drivers = [f"D{n:02d}" for n in range(1, 11)]  # D01-D10
    vendor_of = {d: ("V1" if int(d[1:]) <= 6 else "V2") for d in drivers}
    vehicle_of = {d: f"KA01-{1000 + int(d[1:])}" for d in drivers}
    start = datetime(2026, 10, 1, 7, 0)
    rows = []
    for i in range(1, 121):
        d = rng.choice(drivers)
        sched = start + timedelta(minutes=37 * i)

        late_prob = 0.05
        if d == "D03":  # chronically late driver
            late_prob = 0.6
        if vendor_of[d] == "V2":  # late-prone vendor
            late_prob = max(late_prob, 0.4)
        late = rng.random() < late_prob
        delay = rng.randint(8, 45) if late else rng.randint(-5, 4)

        rating = rng.choice([4, 5, 5, 5, 4, 3])
        if vehicle_of[d] == "KA01-1008":  # poorly rated vehicle
            rating = rng.choice([1, 2, 3, 3, 2])
        rows.append(
            {
                "trip_id": f"T{i:04d}",
                "driver_id": d,
                "vehicle_id": vehicle_of[d],
                "vendor_id": vendor_of[d],
                "scheduled_arrival": sched.isoformat(),
                "actual_arrival": (sched + timedelta(minutes=delay)).isoformat(),
                "rider_rating": rating if rng.random() > 0.05 else "",
                "conduct_flagged": "false",
            }
        )
    rows[41]["conduct_flagged"] = "true"
    rows[41]["rider_rating"] = 1
    return rows


if __name__ == "__main__":
    with (HERE / "trips.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(build())
    print("wrote trips.csv")
