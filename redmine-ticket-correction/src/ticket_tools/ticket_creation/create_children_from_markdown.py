#!/usr/bin/env python3
"""Create Redmine child issues from a Markdown or YAML input.

Examples of supported markdown input:

1) Bullet list
   - タイトルA
   - タイトルB | 内容B

2) Numbered list
   1. タイトルA
   2. タイトルB | 内容B

3) Markdown table (must contain a title/subject column)
   | subject | description |
   |---|---|
   | タイトルA | 内容A |

4) YAML
    tickets:
      - subject: タイトルA
         description: 内容A
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ticket_tools.paths import APP_ROOT
from ticket_tools.ticket_creation.redmine_meeting_importer import (
    RedmineClient as ApiClient,
    require_redmine_api_key,
)


TITLE_KEYS = {"title", "subject", "題名", "件名", "タイトル"}
DESC_KEYS = {"description", "内容", "備考", "詳細"}
TRACKER_KEYS = {"tracker", "トラッカー"}


@dataclass
class RedmineClient:
    base_url: str
    api_key: str
    verify_ssl: bool = True
    ca_bundle: str | None = None
    timeout_seconds: int = 30
    proxy: str | None = None

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = ApiClient(
            self.base_url, self.api_key, self.verify_ssl, self.timeout_seconds,
            ca_bundle=self.ca_bundle, proxy=self.proxy,
        )
        return client.request_json(method, path, payload)

    def list_trackers(self) -> list[dict[str, Any]]:
        data = self._request_json("GET", "trackers.json")
        return data.get("trackers", []) or []

    def tracker_name_to_id_map(self) -> dict[str, int]:
        mapping: dict[str, int] = {}
        trackers = self.list_trackers()
        for tracker in trackers:
            if not isinstance(tracker, dict):
                continue
            tracker_id = tracker.get("id")
            name = str(tracker.get("name", "")).strip().lower()
            if not isinstance(tracker_id, int):
                continue
            if name:
                mapping[name] = tracker_id
            mapping[str(tracker_id)] = tracker_id
        return mapping

    def create_issue(
        self,
        project: str,
        parent_issue_id: int,
        tracker_id: int,
        subject: str,
        description: str,
    ) -> dict[str, Any]:
        payload = {
            "issue": {
                "project_id": project,
                "parent_issue_id": parent_issue_id,
                "tracker_id": tracker_id,
                "subject": subject,
                "description": description,
            }
        }
        return self._request_json("POST", "issues.json", payload)

    def update_issue(
        self,
        issue_id: int,
        parent_issue_id: int,
        tracker_id: int,
        subject: str,
        description: str,
    ) -> dict[str, Any]:
        payload = {
            "issue": {
                "parent_issue_id": parent_issue_id,
                "tracker_id": tracker_id,
                "subject": subject,
                "description": description,
            }
        }
        return self._request_json("PUT", f"issues/{issue_id}.json", payload)

    def list_child_issues(self, project: str, parent_issue_id: int) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            data = self._request_json(
                "GET",
                "issues.json",
                {
                    "project_id": project,
                    "set_filter": 1,
                    "status_id": "*",
                    "f[]": ["parent_id"],
                    "op[parent_id]": "=",
                    "v[parent_id][]": [str(parent_issue_id)],
                    "offset": offset,
                    "limit": limit,
                },
            )
            page = data.get("issues", []) or []
            issues.extend([x for x in page if isinstance(x, dict)])
            total = int(data.get("total_count", len(issues)))
            offset += len(page)
            if offset >= total or not page:
                break

        return issues


def parse_markdown_list_line(line: str) -> dict[str, str] | None:
    line = line.strip()
    if not line:
        return None

    bullet = re.match(r"^[-*+]\s+(.*)$", line)
    number = re.match(r"^\d+\.\s+(.*)$", line)
    m = bullet or number
    if not m:
        return None

    content = m.group(1).strip()
    if not content:
        return None

    parts = [p.strip() for p in content.split("|")]
    if len(parts) == 1:
        return {"subject": parts[0], "description": "", "tracker": ""}
    if len(parts) == 2:
        return {"subject": parts[0], "description": parts[1], "tracker": ""}
    return {"subject": parts[0], "description": parts[1], "tracker": parts[2]}


def split_md_row(line: str) -> list[str]:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return []
    inner = s[1:-1]
    return [c.strip() for c in inner.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) is not None for c in cells)


def parse_markdown_table(text: str) -> list[dict[str, str]]:
    rows = [split_md_row(line) for line in text.splitlines()]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return []

    header = [h.strip().lower() for h in rows[0]]
    if not is_separator_row(rows[1]):
        return []

    title_idx = -1
    desc_idx = -1
    tracker_idx = -1
    for i, key in enumerate(header):
        if key in TITLE_KEYS and title_idx < 0:
            title_idx = i
        if key in DESC_KEYS and desc_idx < 0:
            desc_idx = i
        if key in TRACKER_KEYS and tracker_idx < 0:
            tracker_idx = i

    if title_idx < 0:
        return []

    items: list[dict[str, str]] = []
    for row in rows[2:]:
        if title_idx >= len(row):
            continue
        title = row[title_idx].strip()
        if not title:
            continue
        desc = row[desc_idx].strip() if 0 <= desc_idx < len(row) else ""
        tracker = row[tracker_idx].strip() if 0 <= tracker_idx < len(row) else ""
        items.append({"subject": title, "description": desc, "tracker": tracker})
    return items


def parse_markdown_items(text: str) -> list[dict[str, str]]:
    table_items = parse_markdown_table(text)
    if table_items:
        return table_items

    items: list[dict[str, str]] = []
    for line in text.splitlines():
        parsed = parse_markdown_list_line(line)
        if parsed:
            items.append(parsed)
    return items


def _pick_str(d: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def parse_yaml_items(text: str) -> list[dict[str, str]]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for YAML input. Install with: pip install pyyaml") from exc

    data = yaml.safe_load(text)
    if data is None:
        return []

    nodes: list[Any]
    if isinstance(data, list):
        nodes = data
    elif isinstance(data, dict):
        candidate = data.get("tickets")
        if candidate is None:
            candidate = data.get("items")
        if not isinstance(candidate, list):
            raise RuntimeError("YAML root must be a list, or have a 'tickets'/'items' list.")
        nodes = candidate
    else:
        raise RuntimeError("Unsupported YAML structure.")

    items: list[dict[str, str]] = []
    for node in nodes:
        if isinstance(node, str):
            title = node.strip()
            if title:
                items.append({"subject": title, "description": "", "tracker": ""})
            continue

        if not isinstance(node, dict):
            continue

        title = _pick_str(node, ["subject", "title", "題名", "件名", "タイトル"])
        if not title:
            continue
        desc = _pick_str(node, ["description", "内容", "備考", "詳細"])
        tracker = _pick_str(node, ["tracker", "トラッカー"])
        items.append({"subject": title, "description": desc, "tracker": tracker})

    return items


def parse_input_items(input_path: Path, input_format: str) -> list[dict[str, str]]:
    text = input_path.read_text(encoding="utf-8")

    normalized = input_format.lower().strip()
    if normalized not in {"auto", "markdown", "yaml"}:
        raise RuntimeError("--input-format must be one of: auto, markdown, yaml")

    if normalized == "markdown":
        return parse_markdown_items(text)
    if normalized == "yaml":
        return parse_yaml_items(text)

    suffix = input_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return parse_yaml_items(text)

    md_items = parse_markdown_items(text)
    if md_items:
        return md_items
    return parse_yaml_items(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create Redmine child tickets from Markdown or YAML input."
    )
    parser.add_argument("--base-url", required=True, help="Redmine base URL, e.g. https://redmine.example.local")
    parser.add_argument("--project", required=True, help="Project identifier")
    parser.add_argument("--parent-id", required=True, type=int, help="Parent ticket ID")
    parser.add_argument("--tracker", default="", help="Default tracker name or tracker ID")
    parser.add_argument(
        "--config", type=Path, default=APP_ROOT / "config/config.json",
        help="Connection settings shared with the meeting importer.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input file path (.md/.yaml/.yml) containing child ticket rows",
    )
    parser.add_argument(
        "--input-format",
        default="auto",
        help="Input format: auto (default), markdown, yaml",
    )
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    parser.add_argument("--dry-run", action="store_true", help="Parse and show what would be created")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        api_key = require_redmine_api_key()
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 2

    items = parse_input_items(input_path, args.input_format)
    if not items:
        print("Error: no ticket rows detected from markdown input.", file=sys.stderr)
        return 2

    client = RedmineClient(
        base_url=args.base_url.rstrip("/"),
        api_key=api_key,
        verify_ssl=bool(config.get("verify_ssl", True)) and not args.insecure,
        ca_bundle=config.get("ca_bundle"),
        timeout_seconds=int(config.get("timeout_seconds", 30)),
        proxy=config.get("proxy"),
    )

    tracker_map = client.tracker_name_to_id_map()
    available_trackers = sorted(k for k in tracker_map.keys() if not k.isdigit())
    existing_children = client.list_child_issues(args.project, args.parent_id)

    subject_map: dict[str, list[dict[str, Any]]] = {}
    for issue in existing_children:
        subject = str(issue.get("subject", "")).strip()
        if not subject:
            continue
        subject_map.setdefault(subject, []).append(issue)

    def resolve_tracker_id(raw_value: str, item_index: int) -> int:
        key = raw_value.strip().lower()
        if not key:
            raise RuntimeError(
                f"Tracker is required for item {item_index}. "
                f"Set 'tracker' in input or pass --tracker."
            )
        tracker_id = tracker_map.get(key)
        if tracker_id is None:
            available_text = ", ".join(available_trackers)
            raise RuntimeError(
                f"Invalid tracker '{raw_value}' at item {item_index}. "
                f"Available trackers: {available_text}"
            )
        return tracker_id

    print(f"Parent: #{args.parent_id}")
    print(f"Project: {args.project}")
    print(f"Default tracker: {args.tracker or '(none)'}")
    print(f"Existing children: {len(existing_children)}")
    print(f"Items: {len(items)}")

    if args.dry_run:
        for i, item in enumerate(items, start=1):
            title = item.get("subject", "")
            desc = item.get("description", "")
            tracker_raw = item.get("tracker", "") or args.tracker
            tracker_id = resolve_tracker_id(tracker_raw, i)
            matched = subject_map.get(title, [])
            action = "CREATE"
            suffix_id = ""
            if matched:
                picked = max(
                    matched,
                    key=lambda x: int(x.get("id", 0)) if str(x.get("id", "")).isdigit() else 0,
                )
                action = "UPDATE"
                suffix_id = f" target=#{picked.get('id')}"
            suffix = f" | desc={desc}" if desc else ""
            print(
                f"[DRY-RUN] {i}. {action}{suffix_id} | {title} "
                f"| tracker={tracker_raw} (id={tracker_id}){suffix}"
            )
        return 0

    created: list[int] = []
    updated: list[int] = []
    for i, item in enumerate(items, start=1):
        title = item.get("subject", "")
        desc = item.get("description", "")
        tracker_raw = item.get("tracker", "") or args.tracker
        tracker_id = resolve_tracker_id(tracker_raw, i)
        matched = subject_map.get(title, [])
        if matched:
            picked = max(
                matched,
                key=lambda x: int(x.get("id", 0)) if str(x.get("id", "")).isdigit() else 0,
            )
            existing_id = int(picked.get("id"))
            client.update_issue(
                issue_id=existing_id,
                parent_issue_id=args.parent_id,
                tracker_id=tracker_id,
                subject=title,
                description=desc,
            )
            updated.append(existing_id)
            print(f"Updated #{existing_id}: {title} (tracker={tracker_raw})")
            continue

        res = client.create_issue(
            project=args.project,
            parent_issue_id=args.parent_id,
            tracker_id=tracker_id,
            subject=title,
            description=desc,
        )
        issue = res.get("issue", {}) if isinstance(res, dict) else {}
        issue_id = issue.get("id")
        if issue_id is None:
            raise RuntimeError(f"Unexpected API response while creating item {i}: {res}")
        created_id = int(issue_id)
        created.append(created_id)
        subject_map.setdefault(title, []).append({"id": created_id, "subject": title})
        print(f"Created #{created_id}: {title} (tracker={tracker_raw})")

    print(f"Done. Created {len(created)} / Updated {len(updated)} child tickets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
