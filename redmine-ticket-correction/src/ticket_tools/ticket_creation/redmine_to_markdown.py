#!/usr/bin/env python3
"""Export Redmine project tickets to a Markdown table.

This script retrieves all issues in a project through the Redmine REST API,
expands each issue with detail data, and builds a Markdown table containing
all fields that are actually set in at least one ticket.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from ticket_tools.paths import APP_ROOT
from ticket_tools.ticket_creation.redmine_meeting_importer import (
    RedmineClient as ApiClient,
    require_redmine_api_key,
)


DEFAULT_BASE_COLUMNS = [
    "id",
    "subject",
    "url",
    "tracker",
    "status",
    "priority",
    "author",
    "assigned_to",
    "fixed_version",
    "category",
    "parent_id",
    "start_date",
    "due_date",
    "done_ratio",
    "created_on",
    "updated_on",
    "closed_on",
    "children_count",
    "relations_count",
    "watchers_count",
    "description",
]


@dataclass
class RedmineClient:
    base_url: str
    api_key: str
    verify_ssl: bool = True
    ca_bundle: str | None = None
    timeout_seconds: int = 30
    proxy: str | None = None

    def _request_json(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        client = ApiClient(
            self.base_url, self.api_key, self.verify_ssl, self.timeout_seconds,
            ca_bundle=self.ca_bundle, proxy=self.proxy,
        )
        return client.request_json("GET", path, query)

    def list_issue_ids(self, project_identifier: str, status_id: str = "*") -> list[int]:
        issue_ids: list[int] = []
        offset = 0
        limit = 100

        while True:
            data = self._request_json(
                "issues.json",
                {
                    "project_id": project_identifier,
                    "status_id": status_id,
                    "offset": offset,
                    "limit": limit,
                },
            )
            issues = data.get("issues", [])
            for issue in issues:
                issue_id = issue.get("id")
                if issue_id is not None:
                    issue_ids.append(int(issue_id))

            total = int(data.get("total_count", len(issue_ids)))
            offset += len(issues)
            if offset >= total or not issues:
                break

        return issue_ids

    def get_issue_detail(self, issue_id: int) -> dict[str, Any]:
        data = self._request_json(
            f"issues/{issue_id}.json",
            {
                "include": "children,relations,watchers",
            },
        )
        issue = data.get("issue")
        if not isinstance(issue, dict):
            raise RuntimeError(f"Unexpected response for issue {issue_id}")
        return issue


def normalize_iso_datetime(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value


def is_set(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def md_escape(value: Any) -> str:
    text = str(value)
    text = text.replace("|", r"\|")
    text = text.replace("\n", "<br>")
    return text


def pick_name(node: Any) -> str:
    if isinstance(node, dict):
        for key in ("name", "value", "title"):
            v = node.get(key)
            if is_set(v):
                return str(v)
    return ""


def issue_to_row(issue: dict[str, Any], base_url: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": issue.get("id", ""),
        "subject": issue.get("subject", ""),
        "url": urljoin(base_url.rstrip('/') + '/', f"issues/{issue.get('id', '')}"),
        "tracker": pick_name(issue.get("tracker")),
        "status": pick_name(issue.get("status")),
        "priority": pick_name(issue.get("priority")),
        "author": pick_name(issue.get("author")),
        "assigned_to": pick_name(issue.get("assigned_to")),
        "fixed_version": pick_name(issue.get("fixed_version")),
        "category": pick_name(issue.get("category")),
        "parent_id": (issue.get("parent") or {}).get("id", "")
        if isinstance(issue.get("parent"), dict)
        else "",
        "start_date": issue.get("start_date", ""),
        "due_date": issue.get("due_date", ""),
        "done_ratio": f"{issue.get('done_ratio', '')}%" if is_set(issue.get("done_ratio")) else "",
        "created_on": normalize_iso_datetime(issue.get("created_on")),
        "updated_on": normalize_iso_datetime(issue.get("updated_on")),
        "closed_on": normalize_iso_datetime(issue.get("closed_on")),
        "children_count": len(issue.get("children", []) or []),
        "relations_count": len(issue.get("relations", []) or []),
        "watchers_count": len(issue.get("watcher_users", []) or []),
        "description": issue.get("description", "") or "",
    }

    custom_fields = issue.get("custom_fields", []) or []
    for field in custom_fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name", "")).strip()
        if not name:
            continue
        value = field.get("value")
        if isinstance(value, list):
            row[f"cf:{name}"] = ", ".join(str(v) for v in value if is_set(v))
        else:
            row[f"cf:{name}"] = value or ""

    return row


def build_columns(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return DEFAULT_BASE_COLUMNS

    used = set()
    for row in rows:
        for key, value in row.items():
            if is_set(value):
                used.add(key)

    columns: list[str] = []
    for key in DEFAULT_BASE_COLUMNS:
        if key in used:
            columns.append(key)

    custom_columns = sorted([k for k in used if k.startswith("cf:")])
    columns.extend(custom_columns)

    extras = sorted(k for k in used if k not in set(columns))
    columns.extend(extras)
    return columns


def columns_to_labels(columns: list[str]) -> list[str]:
    labels: list[str] = []
    for c in columns:
        if c.startswith("cf:"):
            labels.append(c[3:])
        else:
            labels.append(c)
    return labels


def rows_to_markdown(rows: list[dict[str, Any]], columns: list[str]) -> str:
    labels = columns_to_labels(columns)
    header = "| " + " | ".join(md_escape(h) for h in labels) + " |"
    separator = "|" + "|".join(["---"] * len(columns)) + "|"

    body_lines = []
    for row in rows:
        values = [md_escape(row.get(c, "")) for c in columns]
        body_lines.append("| " + " | ".join(values) + " |")

    return "\n".join([header, separator, *body_lines])


def grouped_rows_to_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No tickets found."

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tracker = str(row.get("tracker", "")).strip() or "(No Tracker)"
        groups.setdefault(tracker, []).append(row)

    blocks: list[str] = []
    for tracker in sorted(groups.keys()):
        tracker_rows = groups[tracker]
        tracker_rows = sorted(
            tracker_rows,
            key=lambda r: int(r.get("id", 0)) if str(r.get("id", "")).isdigit() else 0,
            reverse=True,
        )
        columns = build_columns(tracker_rows)
        table = rows_to_markdown(tracker_rows, columns)
        blocks.append(f"## {tracker} ({len(tracker_rows)})")
        blocks.append(table)

    return "\n\n".join(blocks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export Redmine issues as a Markdown table with as many set fields as possible."
        )
    )
    parser.add_argument("--base-url", default="", help="Override the configured Redmine base URL.")
    parser.add_argument("--project", required=True, help="Project identifier, e.g. automation_test_project")
    parser.add_argument(
        "--config", type=Path, default=APP_ROOT / "config/config.json",
        help="Connection settings shared with the meeting importer.",
    )
    parser.add_argument(
        "--status-id",
        default="*",
        help="Redmine status filter. Use '*' for all statuses (default).",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output Markdown file path. If omitted, print to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        api_key = require_redmine_api_key()
        config = json.loads(args.config.read_text(encoding="utf-8"))
        base_url = args.base_url or config["redmine_url"]
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    client = RedmineClient(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        verify_ssl=bool(config.get("verify_ssl", True)) and not args.insecure,
        ca_bundle=config.get("ca_bundle"),
        timeout_seconds=int(config.get("timeout_seconds", 30)),
        proxy=config.get("proxy"),
    )

    issue_ids = client.list_issue_ids(args.project, status_id=args.status_id)
    issues = [client.get_issue_detail(issue_id) for issue_id in issue_ids]
    rows = [issue_to_row(issue, base_url.rstrip("/")) for issue in issues]
    markdown = grouped_rows_to_markdown(rows)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(markdown)
            f.write("\n")
        print(f"Wrote {len(rows)} tickets to {args.output}")
    else:
        print(markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
