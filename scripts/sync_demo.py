"""Copy the package and sample data into docs/ so the GitHub Pages demo ships the real code.

Run after changing anything in src/ or sample_data/:  python scripts/sync_demo.py
tests/test_demo.py fails if docs/ drifts out of sync.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FILES = ["__init__.py", "models.py", "rules.py", "engine.py", "store.py"]  # CLI not needed
SAMPLE_FILES = ["trips.csv", "rules.json"]


def main() -> None:
    pkg_dst = ROOT / "docs" / "py" / "penalty_engine"
    pkg_dst.mkdir(parents=True, exist_ok=True)
    for name in PACKAGE_FILES:
        shutil.copyfile(ROOT / "src" / "penalty_engine" / name, pkg_dst / name)

    sample_dst = ROOT / "docs" / "sample"
    sample_dst.mkdir(parents=True, exist_ok=True)
    for name in SAMPLE_FILES:
        shutil.copyfile(ROOT / "sample_data" / name, sample_dst / name)
    print("docs/ synced")


if __name__ == "__main__":
    main()
