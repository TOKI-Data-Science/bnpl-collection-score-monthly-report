from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT_OUTPUT = Path(os.getenv("REPORT_OUTPUT", ROOT / "output" / "bnpl_collection_score_v1.html"))


def run(command: list[str]) -> None:
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True)


def main() -> None:
    if "--dry-run" in sys.argv:
        run(["report.py", "--dry-run"])
        return

    run(["report.py", "--output", str(REPORT_OUTPUT)])
    run(["send_to_power_automate.py", str(REPORT_OUTPUT)])


if __name__ == "__main__":
    main()