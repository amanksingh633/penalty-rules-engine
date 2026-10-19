"""Copy the package and sample data into docs/ so the GitHub Pages demo ships the real code.

Run after changing anything in src/ or sample_data/:  python scripts/sync_demo.py
tests/test_demo.py fails if docs/ drifts out of sync.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FILES = ["__init__.py", "models.py", "rules.py", "engine.py", "store.py"]  # CLI not needed
SAMPLE_FILES = ["trips.csv", "rules.json"]


def write_snapshot() -> None:
    """Pre-compute the sample evaluation so the page can show it before Python has loaded."""
    sys.path.insert(0, str(ROOT / "docs" / "py"))
    import web_entry

    state = json.loads(
        web_entry.start(
            (ROOT / "sample_data" / "trips.csv").read_text(encoding="utf-8"),
            (ROOT / "sample_data" / "rules.json").read_text(encoding="utf-8"),
        )
    )
    state["info"] = "Saved sample run. Python is loading; the buttons unlock when it is ready."
    out = ROOT / "docs" / "sample" / "precomputed.json"
    out.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    pkg_dst = ROOT / "docs" / "py" / "penalty_engine"
    pkg_dst.mkdir(parents=True, exist_ok=True)
    for name in PACKAGE_FILES:
        shutil.copyfile(ROOT / "src" / "penalty_engine" / name, pkg_dst / name)

    sample_dst = ROOT / "docs" / "sample"
    sample_dst.mkdir(parents=True, exist_ok=True)
    for name in SAMPLE_FILES:
        shutil.copyfile(ROOT / "sample_data" / name, sample_dst / name)
    write_snapshot()
    print("docs/ synced")


if __name__ == "__main__":
    main()
