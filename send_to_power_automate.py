from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path


def build_payload(report_path: Path) -> dict[str, str]:
    return {
        "modelName": "BNPL Collection Score V1",
        "reportFileName": report_path.name,
        "reportContentBase64": base64.b64encode(report_path.read_bytes()).decode("ascii"),
        "generatedAt": datetime.now().astimezone().isoformat(),
    }


def send_report(report_path: Path, flow_url: str) -> None:
    request = urllib.request.Request(
        flow_url,
        data=json.dumps(build_payload(report_path)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status not in (200, 202):
            raise RuntimeError(f"Power Automate returned HTTP {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the generated report to a Power Automate flow.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.report.is_file():
        raise FileNotFoundError(f"Report not found: {args.report}")
    if args.dry_run:
        payload = build_payload(args.report)
        print(f"Payload ready: {payload['reportFileName']} ({len(payload['reportContentBase64'])} base64 characters)")
        return
    flow_url = os.getenv("POWER_AUTOMATE_URL")
    if not flow_url:
        raise RuntimeError("Missing POWER_AUTOMATE_URL environment variable")
    send_report(args.report, flow_url)
    print("Report sent to Power Automate")


if __name__ == "__main__":
    main()