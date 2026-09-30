#!/usr/bin/env python3
"""Index Claude transcripts and price only events inside a time window."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def day_bucket(timestamp: datetime, timezone: ZoneInfo, day_start: int) -> str:
    local = timestamp.astimezone(timezone)
    if local.time() < time(hour=day_start):
        local -= timedelta(days=1)
    return local.date().isoformat()


def project_name(path: Path, projects_root: Path) -> str:
    relative = path.relative_to(projects_root)
    return relative.parts[0]


def filtered_transcript(
    path: Path, since: datetime, until: datetime
) -> tuple[list[str], datetime | None, datetime | None]:
    lines: list[str] = []
    first: datetime | None = None
    last: datetime | None = None
    with path.open(errors="replace") as source:
        for line in source:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = parse_timestamp(record.get("timestamp"))
            if timestamp is None or not since <= timestamp <= until:
                continue
            lines.append(line)
            first = timestamp if first is None or timestamp < first else first
            last = timestamp if last is None or timestamp > last else last
    return lines, first, last


def price_transcript(spend: Path, lines: list[str]) -> dict[str, object] | None:
    if not lines:
        return None
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl") as filtered:
        filtered.writelines(lines)
        filtered.flush()
        result = subprocess.run(
            [
                str(spend),
                "cost",
                "--transcript",
                filtered.name,
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True, help="ISO-8601 timestamp")
    parser.add_argument("--until", required=True, help="ISO-8601 timestamp")
    parser.add_argument("--timezone", default="America/Chicago")
    parser.add_argument("--day-start", type=int, choices=range(24), default=6)
    parser.add_argument(
        "--projects-root",
        type=Path,
        default=Path.home() / ".claude" / "projects",
    )
    parser.add_argument(
        "--spend",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "plugins"
            / "context-economy"
            / "scripts"
            / "spend.py"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Only scan transcript paths containing this substring; repeatable",
    )
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since)
    until = datetime.fromisoformat(args.until)
    if since.tzinfo is None or until.tzinfo is None:
        parser.error("--since and --until must include a UTC offset")
    if until < since:
        parser.error("--until must be at or after --since")
    timezone = ZoneInfo(args.timezone)
    paths = [
        path
        for path in sorted(args.projects_root.glob("**/*.jsonl"))
        if not args.include or any(value in str(path) for value in args.include)
    ]

    def inspect(path: Path) -> dict[str, object] | None:
        lines, first, last = filtered_transcript(path, since, until)
        priced = price_transcript(args.spend, lines)
        if priced is None or not priced.get("priced_steps"):
            return None
        models = priced.get("models", {})
        model = ";".join(sorted(models)) if isinstance(models, dict) else ""
        tokens = priced.get("tokens", {})
        return {
            "session": path.stem,
            "date": day_bucket(first, timezone, args.day_start) if first else "",
            "first_event": first.isoformat() if first else "",
            "last_event": last.isoformat() if last else "",
            "project": project_name(path, args.projects_root),
            "coordination_role": "worker" if "subagents" in path.parts else "unknown",
            "models": model,
            "calls": priced.get("priced_steps", 0),
            "input_tokens": tokens.get("in", 0),
            "cache_write_tokens": tokens.get("cache_write", 0),
            "cache_write_1h_tokens": tokens.get("cache_write_1h", 0),
            "cache_read_tokens": tokens.get("cache_read", 0),
            "output_tokens": tokens.get("out", 0),
            "estimated_usd": priced.get("cost", 0),
            "transcript": str(path),
        }

    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = [row for row in executor.map(inspect, paths) if row is not None]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else [
        "session",
        "date",
        "first_event",
        "last_event",
        "project",
        "coordination_role",
        "models",
        "calls",
        "input_tokens",
        "cache_write_tokens",
        "cache_write_1h_tokens",
        "cache_read_tokens",
        "output_tokens",
        "estimated_usd",
        "transcript",
    ]
    with args.output.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"sessions": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
