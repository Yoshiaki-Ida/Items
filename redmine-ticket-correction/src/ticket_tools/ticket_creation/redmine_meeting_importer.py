#!/usr/bin/env python3
"""Import meeting-open-items JSON into Redmine as a new parent and child issues.

Default mode is dry-run. Use --apply to perform API calls.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
from datetime import date, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from ticket_tools.paths import APP_ROOT

DEFAULT_INCLUDE_TYPES = {
    "action_item",
    "investigation",
    "finding",
    "unresolved",
    "confirmation",
    "hold",
}

DEFAULT_EXCLUDE_TYPES = {
    "decision",
    "information",
    "no_action",
    "question",
    "small_talk",
    "undetermined",
}

STANDARD_FIELD_MAP = {
    "ステータス": "status_id",
    "優先度": "priority_id",
    "担当者": "assigned_to_id",
    "対象バージョン": "fixed_version_id",
    "開始日": "start_date",
    "期日": "due_date",
    "進捗率": "done_ratio",
}

RELATIVE_DATE_HINTS = (
    "今週",
    "来週",
    "次回",
    "週間後",
    "復帰後",
    "まで",
    "以降",
)

VALID_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PARENT_ID_PLACEHOLDER = "<created_parent_issue_id>"
CHILD_CUSTOM_FIELD_KEYS = {"処置内容", "確認内容", "確認日", "指摘日"}


class RedmineApiError(RuntimeError):
    """Raised when a Redmine API call fails."""


def _get_windows_user_environment_variable(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except (FileNotFoundError, OSError):
        return ""
    return str(value).strip()


def require_redmine_api_key() -> str:
    """Return the process key, rejecting stale Windows process environments."""
    process_key = os.environ.get("REDMINE_API_KEY", "").strip()
    user_key = _get_windows_user_environment_variable("REDMINE_API_KEY")

    if user_key and not process_key:
        raise RuntimeError(
            "REDMINE_API_KEYはWindowsのユーザー環境変数に登録済みですが、起動中の"
            "プロセスへ反映されていません。VS Code/Copilot本体を完全に終了して再起動し、"
            "元の依頼をもう一度送ってください。新しいチャットやCheckpoint Redoだけでは"
            "反映されません。APIキーの再登録や設定用BATの実行は不要です。"
            "offline／ローカル処理への切替は行っていません。"
        )
    if user_key and process_key != user_key:
        raise RuntimeError(
            "起動中のプロセスが、Windowsのユーザー環境変数とは異なる古い"
            "REDMINE_API_KEYを保持しています。VS Code/Copilot本体を完全に終了して"
            "再起動し、元の依頼をもう一度送ってください。新しいチャットやCheckpoint "
            "Redoだけでは更新されません。APIキーの再登録や設定用BATの実行は不要です。"
            "offline／ローカル処理への切替は行っていません。"
        )
    if not process_key:
        raise RuntimeError(
            "REDMINE_API_KEYが登録されていません。"
            "[Environment]::SetEnvironmentVariable(\"REDMINE_API_KEY\", \"<APIキー>\", "
            "\"User\") をPowerShellで一度実行し、VS Code/Copilot本体を再起動してから"
            "元の依頼をもう一度送ってください。APIキーをチャットやコマンド引数へ"
            "入力しないでください。offline／ローカル処理への切替は行っていません。"
        )
    return process_key


def _redmine_http_error_message(
    code: int,
    method: str,
    url: str,
    detail: str,
) -> str:
    base = f"HTTP {code} {method} {url} body={detail[:1000]}"
    if code == 401:
        return (
            f"{base}。認証に失敗しました。起動中のプロセスが読み込んだ"
            "REDMINE_API_KEYはRedmineに拒否されました。APIキーを最近登録・更新した場合は、"
            "VS Code/Copilot本体を完全に終了して再起動してください。新しいチャットや"
            "Checkpoint Redoだけでは更新されません。再起動済みの場合は、Windowsの"
            "ユーザー環境変数に登録したAPIキーを更新してください。APIキー設定用BATの実行や"
            "offline／ローカルデータへの切替は行わないでください。"
        )
    if code == 403:
        return (
            f"{base}。認可に失敗しました。RedmineアカウントとAPIアクセスが有効で、"
            "対象リソースを参照する権限があるか確認してください。"
            "offline／ローカルデータへ切り替えないでください。"
        )
    return base


@dataclass
class RuntimeSettings:
    redmine_url: str
    verify_ssl: bool
    ca_bundle: str | None
    timeout_seconds: int
    proxy: str | None
    formatter: str
    parent_subject_prefix: str
    parent_subject_suffix: str
    continue_on_child_error: bool


@dataclass
class BuildContext:
    warnings: list[str]
    unresolved_values: list[dict[str, Any]]
    unset_custom_fields: list[dict[str, Any]]


class TextFormatter:
    def __init__(self, kind: str) -> None:
        normalized = kind.strip().lower()
        if normalized not in {"markdown", "textile"}:
            normalized = "markdown"
        self.kind = normalized

    def heading(self, title: str) -> str:
        if self.kind == "textile":
            return f"h2. {title}"
        return f"## {title}"

    def bullet(self, text: str) -> str:
        if self.kind == "textile":
            return f"* {text}"
        return f"- {text}"

    def key_value(self, key: str, value: str) -> str:
        if self.kind == "textile":
            return f"*{key}*: {value}"
        return f"- **{key}**: {value}"


class RedmineClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        verify_ssl: bool,
        timeout_seconds: int,
        ca_bundle: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout_seconds = timeout_seconds
        self.ca_bundle = ca_bundle
        self.proxy = proxy

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self.verify_ssl:
            if self.ca_bundle:
                return ssl.create_default_context(cafile=self.ca_bundle)
            return None
        return ssl._create_unverified_context()

    def _build_opener(self):
        handlers = []
        context = self._ssl_context()
        if context is not None:
            handlers.append(HTTPSHandler(context=context))
        if self.proxy:
            handlers.append(ProxyHandler({"http": self.proxy, "https": self.proxy}))
        return build_opener(*handlers)

    def request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request_method = method.upper()
        query = None
        if request_method == "GET" and payload is not None:
            query = urlencode(payload, doseq=True)
        full_path = f"{path}?{query}" if query else path
        url = urljoin(self.base_url + "/", full_path.lstrip("/"))

        body = None
        if request_method != "GET" and payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = Request(url, data=body, method=request_method)
        req.add_header("X-Redmine-API-Key", self.api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        opener = self._build_opener()
        try:
            with opener.open(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                if not raw.strip():
                    return {}
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise RedmineApiError(
                        f"Unexpected response JSON type: {type(parsed).__name__} {request_method} {url}"
                    )
                return parsed
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RedmineApiError(
                _redmine_http_error_message(exc.code, request_method, url, detail)
            ) from exc
        except URLError as exc:
            raise RedmineApiError(f"Connection error {request_method} {url}: {exc.reason}") from exc

    def create_issue(self, issue_payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/issues.json", {"issue": issue_payload})

    def update_issue(self, issue_id: int, issue_payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json("PUT", f"/issues/{issue_id}.json", {"issue": issue_payload})

    def find_issues_by_subject(self, project_id: str, subject: str, limit: int = 20) -> list[dict[str, Any]]:
        data = self.request_json(
            "GET",
            "/issues.json",
            {
                "project_id": project_id,
                "status_id": "*",
                "subject": subject,
                "limit": limit,
            },
        )
        rows = data.get("issues", [])
        if not isinstance(rows, list):
            return []
        return [x for x in rows if isinstance(x, dict)]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import meeting-open-items JSON to Redmine")
    parser.add_argument("input_json", help="meeting-open-items JSON path")
    parser.add_argument("--config", required=True, help="Config JSON path")
    parser.add_argument("--base-url", help="Override Redmine base URL from config")
    parser.add_argument("--project-id", required=True, help="Redmine project id or identifier")
    parser.add_argument("--parent-tracker-id", required=True, type=int, help="Parent issue tracker ID")
    parser.add_argument("--child-tracker-id", required=True, type=int, help="Child issue tracker ID")
    parser.add_argument("--registration-options", type=Path, help="Verified project/tracker candidates JSON (optional labels)")
    parser.add_argument(
        "--include-types",
        default=",".join(sorted(DEFAULT_INCLUDE_TYPES)),
        help="Comma-separated item types to include",
    )
    parser.add_argument(
        "--include-not-ready",
        action="store_true",
        help="Include ticket_readiness=not_ready items",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply to Redmine. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--confirm-create-parent",
        action="store_true",
        help="Required with --apply to confirm creating a new parent issue.",
    )
    parser.add_argument(
        "--output",
        default=str(APP_ROOT / "output/redmine-ticket-creation/redmine-import-result.json"),
        help="Result JSON output path",
    )
    return parser.parse_args(argv)


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    if isinstance(value, dict) and len(value) == 0:
        return True
    return False


def parse_iso_date_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if not VALID_DATE_PATTERN.match(text):
        return None
    return text


def should_treat_as_relative_date(text: str) -> bool:
    for hint in RELATIVE_DATE_HINTS:
        if hint in text:
            return True
    return False


def parse_int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def require_int_mapping(mapping: dict[str, Any], key: str) -> int | None:
    raw = mapping.get(key)
    return parse_int_or_none(raw)


def normalize_map_keys(mapping: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized[str(key).strip().lower()] = value
    return normalized


def normalize_person_name_key(value: str) -> str:
    # Treat half/full-width spaces uniformly for name matching.
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip().lower()


def resolve_assignee_user_id(value: str, user_ids_config: dict[str, Any]) -> int | None:
    user_ids = {normalize_person_name_key(str(k)): v for k, v in user_ids_config.items()}
    normalized_value = normalize_person_name_key(value)
    if not normalized_value:
        return None

    candidates: list[str] = [normalized_value, normalized_value.replace(" ", "")]

    # Surname-first fallback.
    if " " in normalized_value:
        surname = normalized_value.split(" ", 1)[0].strip()
        if surname:
            candidates.append(surname)

    for key in candidates:
        mapped = require_int_mapping(user_ids, key)
        if mapped is not None:
            return mapped

    # Final fallback for no-space full names if config uses surname keys.
    compact = normalized_value.replace(" ", "")
    prefix_matches = [
        require_int_mapping(user_ids, key)
        for key in user_ids.keys()
        if key and len(key) >= 2 and compact.startswith(key)
    ]
    prefix_matches = [x for x in prefix_matches if x is not None]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def ensure_required_top_level(data: dict[str, Any]) -> None:
    required = [
        "meeting",
        "meeting_summary",
        "redmine_meeting_fields",
        "summary",
        "items",
        "human_review_required",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        raise RuntimeError(f"Missing required top-level keys: {', '.join(missing)}")


def render_section_lines(title: str, lines: list[str], formatter: TextFormatter) -> list[str]:
    out: list[str] = [formatter.heading(title)]
    if not lines:
        out.append(formatter.bullet("(なし)"))
        return out
    for line in lines:
        out.append(formatter.bullet(line))
    return out


def build_parent_description(data: dict[str, Any], formatter: TextFormatter) -> str:
    meeting = safe_dict(data.get("meeting"))
    summary = safe_dict(data.get("meeting_summary"))
    count_summary = safe_dict(data.get("summary"))
    human_review_required = safe_list(data.get("human_review_required"))

    overview = str(summary.get("overview", "")).strip()
    main_topics = [str(x).strip() for x in safe_list(summary.get("main_topics")) if str(x).strip()]
    key_outcomes = [str(x).strip() for x in safe_list(summary.get("key_outcomes")) if str(x).strip()]
    open_points = [str(x).strip() for x in safe_list(summary.get("open_points")) if str(x).strip()]
    next_step = str(summary.get("next_step_summary", "")).strip()

    meeting_info_lines: list[str] = []
    for key in ["title", "project", "datetime", "transcript_source", "extracted_at"]:
        value = meeting.get(key)
        if not is_empty_value(value):
            meeting_info_lines.append(f"{key}: {value}")

    extraction_lines: list[str] = []
    for k in [
        "decision_count",
        "action_item_count",
        "investigation_count",
        "finding_count",
        "unresolved_count",
        "confirmation_count",
        "hold_count",
        "no_action_count",
        "information_count",
        "ticket_ready_count",
        "needs_human_review_count",
    ]:
        value = count_summary.get(k)
        if not is_empty_value(value):
            extraction_lines.append(f"{k}: {value}")

    human_lines: list[str] = []
    for row in human_review_required:
        if isinstance(row, dict):
            item_id = row.get("item_id") or row.get("id")
            reason = row.get("reason") or row.get("note")
            detail = " / ".join([str(x).strip() for x in [item_id, reason] if str(x).strip()])
            if detail:
                human_lines.append(detail)
        elif isinstance(row, str) and row.strip():
            human_lines.append(row.strip())

    lines: list[str] = []
    lines.extend(render_section_lines("会議全体の要旨", [overview] if overview else [], formatter))
    lines.extend(render_section_lines("主な議題", main_topics, formatter))
    lines.extend(render_section_lines("主な決定・対応・調査事項", key_outcomes, formatter))
    lines.extend(render_section_lines("未決・確認待ち事項", open_points, formatter))
    lines.extend(render_section_lines("次の進め方", [next_step] if next_step else [], formatter))
    lines.extend(render_section_lines("会議情報", meeting_info_lines, formatter))
    lines.extend(render_section_lines("抽出件数", extraction_lines, formatter))
    lines.extend(render_section_lines("人間確認が必要な事項", human_lines, formatter))
    return "\n".join(lines).strip() + "\n"


def build_item_description(item: dict[str, Any], formatter: TextFormatter) -> str:
    _ = formatter  # Kept for API compatibility; child description format is fixed by schema v1.6.
    from .meeting_registration import optional_text, evidence_paragraph, separate_evidence

    description = optional_text(item.get("description"))
    rationale = optional_text(item.get("rationale"))
    expected_state = optional_text(item.get("expected_state"))
    evidence = evidence_paragraph(item.get("evidence"))
    rationale, evidence = separate_evidence(rationale, evidence)

    lines: list[str] = []
    if description:
        lines.append(description)
    if rationale:
        if lines:
            lines.append("")
        lines.append("理由・背景:")
        lines.append(rationale)
    if evidence:
        if lines:
            lines.append("")
        lines.append(evidence)
    if expected_state:
        if lines:
            lines.append("")
        lines.append("期待状態:")
        lines.append(expected_state)

    if not lines:
        return ""
    return "\n".join(lines).strip() + "\n"


def map_standard_field(
    field_name: str,
    value: Any,
    config: dict[str, Any],
    context: BuildContext,
    item_id: str,
) -> tuple[str, Any] | None:
    target_key = STANDARD_FIELD_MAP[field_name]

    if target_key == "assigned_to_id":
        if isinstance(value, int):
            return (target_key, value)
        if isinstance(value, str):
            mapped = resolve_assignee_user_id(value, safe_dict(config.get("user_ids")))
            if mapped is not None:
                return (target_key, mapped)
            context.unresolved_values.append(
                {"item_id": item_id, "field": field_name, "value": value, "reason": "user_id_not_mapped"}
            )
        return None

    if target_key == "status_id":
        if isinstance(value, int):
            return (target_key, value)
        if isinstance(value, str):
            mapped = require_int_mapping(
                normalize_map_keys(safe_dict(config.get("status_ids"))),
                value.strip().lower(),
            )
            if mapped is not None:
                return (target_key, mapped)
            context.unresolved_values.append(
                {"item_id": item_id, "field": field_name, "value": value, "reason": "status_id_not_mapped"}
            )
        return None

    if target_key == "priority_id":
        if isinstance(value, int):
            return (target_key, value)
        if isinstance(value, str):
            mapped = require_int_mapping(
                normalize_map_keys(safe_dict(config.get("priority_ids"))),
                value.strip().lower(),
            )
            if mapped is not None:
                return (target_key, mapped)
            context.unresolved_values.append(
                {"item_id": item_id, "field": field_name, "value": value, "reason": "priority_id_not_mapped"}
            )
        return None

    if target_key in {"start_date", "due_date"}:
        if isinstance(value, str) and should_treat_as_relative_date(value):
            return None
        parsed = parse_iso_date_or_none(value)
        if parsed is not None:
            return (target_key, parsed)
        if not is_empty_value(value):
            context.unresolved_values.append(
                {"item_id": item_id, "field": field_name, "value": value, "reason": "invalid_date_format"}
            )
        return None

    if target_key == "done_ratio":
        ratio = parse_int_or_none(value)
        if ratio is None:
            return None
        if 0 <= ratio <= 100:
            return (target_key, ratio)
        context.unresolved_values.append(
            {"item_id": item_id, "field": field_name, "value": value, "reason": "done_ratio_out_of_range"}
        )
        return None

    if target_key == "fixed_version_id":
        mapped = parse_int_or_none(value)
        if mapped is not None:
            return (target_key, mapped)
        if isinstance(value, str):
            mapped = require_int_mapping(
                normalize_map_keys(safe_dict(config.get("version_ids"))),
                value.strip().lower(),
            )
            if mapped is not None:
                return (target_key, mapped)
            context.unresolved_values.append(
                {"item_id": item_id, "field": field_name, "value": value, "reason": "version_id_not_mapped"}
            )
        return None

    return None


def map_redmine_fields(
    source_fields: dict[str, Any],
    config: dict[str, Any],
    context: BuildContext,
    item_id: str,
    custom_field_whitelist: set[str] | None = None,
) -> dict[str, Any]:
    issue_fields: dict[str, Any] = {}
    custom_fields_payload: list[dict[str, Any]] = []
    custom_field_ids = safe_dict(config.get("custom_field_ids"))

    for field_name, raw_value in source_fields.items():
        if is_empty_value(raw_value):
            continue

        if field_name in STANDARD_FIELD_MAP:
            mapped = map_standard_field(field_name, raw_value, config, context, item_id)
            if mapped is not None:
                key, value = mapped
                issue_fields[key] = value
            continue

        if custom_field_whitelist is not None and field_name not in custom_field_whitelist:
            continue

        if field_name == "確認日":
            parsed_date = parse_iso_date_or_none(raw_value)
            if parsed_date is None:
                context.unresolved_values.append(
                    {"item_id": item_id, "field": field_name, "value": raw_value, "reason": "invalid_date_format"}
                )
                continue
            raw_value = parsed_date

        custom_id = parse_int_or_none(custom_field_ids.get(field_name))
        if custom_id is None:
            context.unset_custom_fields.append(
                {"item_id": item_id, "field": field_name, "value": raw_value}
            )
            continue

        custom_fields_payload.append({"id": custom_id, "value": raw_value})

    if custom_fields_payload:
        issue_fields["custom_fields"] = custom_fields_payload
    return issue_fields


def upsert_custom_field(issue_fields: dict[str, Any], custom_id: int, value: Any) -> None:
    if is_empty_value(value):
        return
    current = issue_fields.get("custom_fields")
    if not isinstance(current, list):
        current = []
        issue_fields["custom_fields"] = current

    for row in current:
        if isinstance(row, dict) and parse_int_or_none(row.get("id")) == custom_id:
            row["value"] = value
            return

    current.append({"id": custom_id, "value": value})


def get_custom_field_value(issue_fields: dict[str, Any], custom_id: int) -> Any:
    current = issue_fields.get("custom_fields")
    if not isinstance(current, list):
        return None
    for row in current:
        if isinstance(row, dict) and parse_int_or_none(row.get("id")) == custom_id:
            return row.get("value")
    return None


def apply_default_child_dates(issue_fields: dict[str, Any], config: dict[str, Any], run_date: date) -> None:
    custom_field_ids = safe_dict(config.get("custom_field_ids"))

    pointed_out_id = parse_int_or_none(custom_field_ids.get("指摘日"))
    if pointed_out_id is not None:
        existing = get_custom_field_value(issue_fields, pointed_out_id)
        if is_empty_value(existing):
            upsert_custom_field(issue_fields, pointed_out_id, run_date.isoformat())


def apply_provisional_confirm_date_if_unreadable(
    issue_fields: dict[str, Any],
    source_fields: dict[str, Any],
    config: dict[str, Any],
    context: BuildContext,
    item_id: str,
    run_date: date,
) -> None:
    custom_field_ids = safe_dict(config.get("custom_field_ids"))
    confirm_date_id = parse_int_or_none(custom_field_ids.get("確認日"))
    if confirm_date_id is None:
        return

    existing = get_custom_field_value(issue_fields, confirm_date_id)
    if not is_empty_value(existing):
        return

    raw_confirm_date = source_fields.get("確認日")
    if is_empty_value(raw_confirm_date):
        return

    provisional = (run_date + timedelta(days=7)).isoformat()
    upsert_custom_field(issue_fields, confirm_date_id, provisional)
    context.warnings.append(
        f"{item_id}: 確認日の値を解釈できなかったため暫定値を設定しました value='{raw_confirm_date}' provisional='{provisional}'"
    )


def parse_include_types(raw: str) -> set[str]:
    types = {x.strip() for x in raw.split(",") if x.strip()}
    return types or set(DEFAULT_INCLUDE_TYPES)


def is_item_eligible(item: dict[str, Any], include_types: set[str], include_not_ready: bool) -> tuple[bool, str | None]:
    item_type = str(item.get("type", "")).strip()
    readiness = str(item.get("ticket_readiness", "")).strip()

    if item_type in DEFAULT_EXCLUDE_TYPES and item_type not in include_types:
        return (False, f"type_excluded:{item_type}")

    if item_type not in include_types:
        return (False, f"type_not_included:{item_type}")

    if not include_not_ready and readiness == "not_ready":
        return (False, "ticket_readiness_not_ready")

    item_id = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    if not item_id:
        return (False, "missing_item_id")
    if not title:
        return (False, "missing_title")

    return (True, None)


def make_child_subject(item: dict[str, Any]) -> str:
    return f"[{str(item.get('id', '')).strip()}] {str(item.get('title', '')).strip()}"


def make_parent_subject(data: dict[str, Any], runtime: RuntimeSettings) -> str:
    meeting = safe_dict(data.get("meeting"))
    base_title = str(meeting.get("title", "")).strip() or "会議議事録"
    return f"{runtime.parent_subject_prefix}{base_title}{runtime.parent_subject_suffix}".strip()


def build_parent_issue_payload(
    data: dict[str, Any],
    config: dict[str, Any],
    formatter: TextFormatter,
    context: BuildContext,
    project_id: str,
    parent_tracker_id: int,
    parent_subject: str,
) -> dict[str, Any]:
    payload = map_redmine_fields(
        safe_dict(data.get("redmine_meeting_fields")),
        config,
        context,
        item_id="PARENT",
    )
    payload.update(
        {
            "project_id": project_id,
            "tracker_id": parent_tracker_id,
            "subject": parent_subject,
            "description": build_parent_description(data, formatter),
        }
    )
    return payload


def build_child_issue_payload(
    item: dict[str, Any],
    config: dict[str, Any],
    formatter: TextFormatter,
    context: BuildContext,
    project_id: str,
    parent_issue_id: int | str,
    child_tracker_id: int,
    run_date: date | None = None,
) -> dict[str, Any]:
    item_id = str(item.get("id", "")).strip()
    source_fields = safe_dict(item.get("redmine_issue_fields"))
    payload: dict[str, Any] = {
        "project_id": project_id,
        "parent_issue_id": parent_issue_id,
        "tracker_id": child_tracker_id,
        "subject": make_child_subject(item),
        "description": build_item_description(item, formatter),
    }
    payload.update(
        map_redmine_fields(
            source_fields,
            config,
            context,
            item_id=item_id,
            custom_field_whitelist=CHILD_CUSTOM_FIELD_KEYS,
        )
    )
    effective_run_date = run_date or date.today()
    apply_default_child_dates(payload, config, effective_run_date)
    apply_provisional_confirm_date_if_unreadable(
        payload,
        source_fields,
        config,
        context,
        item_id,
        effective_run_date,
    )
    return payload


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Input file not found: {path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON format: {path} line={exc.lineno} col={exc.colno}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Top-level JSON must be an object")
    return parsed


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Config file not found: {path}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid config JSON: {path} line={exc.lineno} col={exc.colno}") from exc
    if not isinstance(cfg, dict):
        raise RuntimeError("Config JSON must be an object")
    return cfg


def make_runtime_settings(config: dict[str, Any], base_url_override: str | None = None) -> RuntimeSettings:
    redmine_url = str(base_url_override or config.get("redmine_url", "")).strip()
    if not redmine_url:
        raise RuntimeError("redmine_url is required in config")

    timeout = parse_int_or_none(config.get("timeout_seconds", 30))
    if timeout is None or timeout <= 0:
        raise RuntimeError("timeout_seconds must be a positive integer")

    formatter = str(config.get("description_format", "markdown")).strip().lower()
    if formatter not in {"markdown", "textile"}:
        raise RuntimeError("description_format must be markdown or textile")

    ca_bundle = config.get("ca_bundle")
    if ca_bundle is not None and not isinstance(ca_bundle, str):
        raise RuntimeError("ca_bundle must be string or null")

    proxy = config.get("proxy")
    if proxy is not None and not isinstance(proxy, str):
        raise RuntimeError("proxy must be string or null")

    return RuntimeSettings(
        redmine_url=redmine_url,
        verify_ssl=bool(config.get("verify_ssl", True)),
        ca_bundle=ca_bundle,
        timeout_seconds=timeout,
        proxy=proxy,
        formatter=formatter,
        parent_subject_prefix=str(config.get("parent_subject_prefix", "")),
        parent_subject_suffix=str(config.get("parent_subject_suffix", " 議事録")),
        continue_on_child_error=bool(config.get("continue_on_child_error", True)),
    )


def validate_config_ids(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section in ["custom_field_ids", "user_ids", "status_ids", "priority_ids", "version_ids"]:
        mapping = config.get(section)
        if mapping is None:
            continue
        if not isinstance(mapping, dict):
            errors.append(f"{section} must be an object")
            continue
        for key, value in mapping.items():
            if value is None:
                continue
            if parse_int_or_none(value) is None:
                errors.append(f"{section}.{key} must be integer or numeric string")
    return errors


def collect_candidate_children(
    input_data: dict[str, Any],
    include_types: set[str],
    include_not_ready: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    included_items: list[dict[str, Any]] = []
    skipped_items: list[dict[str, Any]] = []
    seen_item_ids: set[str] = set()

    for row in safe_list(input_data.get("items")):
        if not isinstance(row, dict):
            skipped_items.append({"item_id": None, "reason": "item_not_object"})
            continue

        item_id = str(row.get("id", "")).strip() or None
        if item_id and item_id in seen_item_ids:
            skipped_items.append({"item_id": item_id, "reason": "duplicate_item_id_in_input"})
            continue

        eligible, reason = is_item_eligible(row, include_types, include_not_ready)
        if not eligible:
            skipped_items.append({"item_id": item_id, "reason": reason})
            continue

        if item_id:
            seen_item_ids.add(item_id)
        included_items.append(row)

    return included_items, skipped_items


def safe_write_json(path: str, payload: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_invalid_assignee_error(exc: Exception) -> bool:
    text = str(exc)
    return ("担当者 は不正な値です" in text) or ("assigned_to" in text.lower() and "invalid" in text.lower())


def build_failure_detail(
    item_id: str,
    action: str,
    subject: str,
    assigned_to_id: int | None,
    issue_id: int | None,
    error: str,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "action": action,
        "subject": subject,
        "assigned_to_id": assigned_to_id,
        "issue_id": issue_id,
        "error": error,
    }


def pick_latest_issue_id(issues: list[dict[str, Any]]) -> int | None:
    candidate_ids = [parse_int_or_none(x.get("id")) for x in issues]
    valid_ids = [x for x in candidate_ids if x is not None]
    if not valid_ids:
        return None
    return max(valid_ids)


def ask_yes_no(message: str) -> bool:
    raw = input(message).strip().lower()
    return raw in {"y", "yes"}


def ask_duplicate_action(subject: str, issue_ids: list[int], kind: str) -> str:
    id_text = ", ".join(str(x) for x in issue_ids)
    print(f"[DUPLICATE] {kind} subject already exists: {subject}")
    if id_text:
        print(f"[DUPLICATE] Existing issue IDs: {id_text}")

    if ask_yes_no("上書き(更新)しますか? [y/N]: "):
        return "update"
    if ask_yes_no("新規作成しますか? [y/N]: "):
        return "create"
    return "skip"


def run(argv: list[str]) -> int:
    args = parse_args(argv)
    output_path = Path(args.output)
    preview_path = output_path.with_suffix(".html")
    if not args.apply and (
        output_path.suffix.lower() == ".html" or output_path.resolve() == preview_path.resolve()
    ):
        raise ValueError("JSON output and HTML preview paths must differ; use a .json output path")
    input_data = read_json_file(Path(args.input_json))
    ensure_required_top_level(input_data)

    config = load_config(Path(args.config))
    runtime = make_runtime_settings(config, base_url_override=args.base_url)
    from .meeting_registration import load_labels, render_registration_preview

    labels = load_labels(args.registration_options, runtime.redmine_url,
                         args.project_id, args.parent_tracker_id, args.child_tracker_id)

    id_errors = validate_config_ids(config)
    if id_errors:
        raise RuntimeError("Invalid config IDs: " + "; ".join(id_errors))

    if args.apply and not args.confirm_create_parent:
        raise RuntimeError("--confirm-create-parent is required when --apply is used")

    api_key = require_redmine_api_key() if args.apply else ""

    include_types = parse_include_types(args.include_types)
    formatter = TextFormatter(runtime.formatter)
    context = BuildContext(warnings=[], unresolved_values=[], unset_custom_fields=[])
    execution_date = date.today()

    parent_subject = make_parent_subject(input_data, runtime)
    parent_payload = build_parent_issue_payload(
        input_data,
        config,
        formatter,
        context,
        project_id=args.project_id,
        parent_tracker_id=args.parent_tracker_id,
        parent_subject=parent_subject,
    )

    included_items, skipped_items = collect_candidate_children(
        input_data,
        include_types,
        args.include_not_ready,
    )

    if not args.apply:
        child_templates: list[dict[str, Any]] = []
        for row in included_items:
            item_id = str(row.get("id", "")).strip()
            child_templates.append(
                {
                    "item_id": item_id,
                    "payload_template": build_child_issue_payload(
                        row,
                        config,
                        formatter,
                        context,
                        project_id=args.project_id,
                        parent_issue_id=PARENT_ID_PLACEHOLDER,
                        child_tracker_id=args.child_tracker_id,
                        run_date=execution_date,
                    ),
                }
            )

        dry_result = {
            "mode": "dry-run",
            "parent": {
                "payload": parent_payload,
            },
            "children": child_templates,
            "skipped_items": skipped_items,
            "warnings": context.warnings,
            "unset_custom_fields": context.unset_custom_fields,
            "unresolved_mappings": context.unresolved_values,
        }
        safe_write_json(args.output, dry_result)
        preview_path.write_text(render_registration_preview(dry_result, runtime.redmine_url, labels, config), encoding="utf-8")
        print(f"Dry-run completed. Result written: {args.output}")
        print(f"登録ドラフト（まだRedmineには登録されていません）: {preview_path}")
        return 0

    client = RedmineClient(
        base_url=runtime.redmine_url,
        api_key=api_key,
        verify_ssl=runtime.verify_ssl,
        timeout_seconds=runtime.timeout_seconds,
        ca_bundle=runtime.ca_bundle,
        proxy=runtime.proxy,
    )

    same_subject = client.find_issues_by_subject(args.project_id, parent_subject)

    failed_items: list[dict[str, Any]] = []
    created_children: list[dict[str, Any]] = []

    parent_action = "created"
    created_parent_issue_id: int | None = None
    updated_parent_issue_id: int | None = None

    try:
        if same_subject:
            existing_ids = [x for x in [parse_int_or_none(i.get("id")) for i in same_subject] if x is not None]
            selected = ask_duplicate_action(parent_subject, existing_ids, "parent")
            if selected == "skip":
                parent_action = "skipped"
                result = {
                    "mode": "apply",
                    "parent": {
                        "created_issue_id": None,
                        "updated_issue_id": None,
                        "subject": parent_subject,
                        "action": parent_action,
                    },
                    "children": [],
                    "skipped_items": skipped_items,
                    "failed_items": failed_items,
                    "warnings": context.warnings,
                    "unset_custom_fields": context.unset_custom_fields,
                    "unresolved_mappings": context.unresolved_values,
                }
                safe_write_json(args.output, result)
                print(f"Apply completed. Result written: {args.output}")
                return 0

            if selected == "update":
                target_id = pick_latest_issue_id(same_subject)
                if target_id is None:
                    raise RuntimeError("Duplicate parent found but issue id is invalid")
                update_payload = dict(parent_payload)
                update_payload.pop("project_id", None)
                client.update_issue(target_id, update_payload)
                parent_issue_id = target_id
                parent_action = "updated"
                updated_parent_issue_id = target_id
            else:
                parent_res = client.create_issue(parent_payload)
                parent_issue = safe_dict(parent_res.get("issue"))
                parent_issue_id = parse_int_or_none(parent_issue.get("id"))
                if parent_issue_id is None:
                    raise RuntimeError("Parent creation response does not contain issue.id")
                created_parent_issue_id = parent_issue_id
        else:
            parent_res = client.create_issue(parent_payload)
            parent_issue = safe_dict(parent_res.get("issue"))
            parent_issue_id = parse_int_or_none(parent_issue.get("id"))
            if parent_issue_id is None:
                raise RuntimeError("Parent creation response does not contain issue.id")
            created_parent_issue_id = parent_issue_id
    except Exception as exc:  # noqa: BLE001
        fail_result = {
            "mode": "apply",
            "parent": {
                "created_issue_id": None,
                "updated_issue_id": None,
                "subject": parent_subject,
                "action": "failed",
                "error": str(exc),
            },
            "children": [],
            "skipped_items": skipped_items,
            "failed_items": failed_items,
            "warnings": context.warnings,
            "unset_custom_fields": context.unset_custom_fields,
            "unresolved_mappings": context.unresolved_values,
        }
        safe_write_json(args.output, fail_result)
        raise RuntimeError(f"Failed to create/update parent issue: {exc}") from exc

    for row in included_items:
        item_id = str(row.get("id", "")).strip()
        payload = build_child_issue_payload(
            row,
            config,
            formatter,
            context,
            project_id=args.project_id,
            parent_issue_id=parent_issue_id,
            child_tracker_id=args.child_tracker_id,
            run_date=execution_date,
        )
        subject = str(payload.get("subject", ""))
        payload_assignee = parse_int_or_none(payload.get("assigned_to_id"))

        child_same_subject = client.find_issues_by_subject(args.project_id, subject)

        if child_same_subject:
            existing_ids = [x for x in [parse_int_or_none(i.get("id")) for i in child_same_subject] if x is not None]
            selected = ask_duplicate_action(str(payload.get("subject", "")), existing_ids, "child")
            if selected == "skip":
                skipped_items.append({"item_id": item_id, "reason": "duplicate_subject_skip"})
                context.warnings.append(
                    f"{item_id}: duplicate action=skip subject='{subject}' assignee={payload_assignee}"
                )
                continue
            if selected == "update":
                target_id = pick_latest_issue_id(child_same_subject)
                if target_id is None:
                    failed_items.append(
                        build_failure_detail(
                            item_id=item_id,
                            action="update",
                            subject=subject,
                            assigned_to_id=payload_assignee,
                            issue_id=None,
                            error="duplicate child found but issue id is invalid",
                        )
                    )
                    if not runtime.continue_on_child_error:
                        break
                    continue
                update_payload = dict(payload)
                update_payload.pop("project_id", None)
                try:
                    client.update_issue(target_id, update_payload)
                    created_children.append(
                        {
                            "item_id": item_id,
                            "updated_issue_id": target_id,
                            "subject": payload.get("subject", ""),
                        }
                    )
                    continue
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, RedmineApiError):
                        raise
                    if "assigned_to_id" in update_payload and is_invalid_assignee_error(exc):
                        retry_payload = dict(update_payload)
                        retry_payload.pop("assigned_to_id", None)
                        try:
                            client.update_issue(target_id, retry_payload)
                            created_children.append(
                                {
                                    "item_id": item_id,
                                    "updated_issue_id": target_id,
                                    "subject": subject,
                                }
                            )
                            context.warnings.append(
                                f"{item_id}: retry success action=update_retry_without_assignee issue_id={target_id} "
                                f"subject='{subject}' removed_assignee={payload_assignee}"
                            )
                            continue
                        except Exception as retry_exc:  # noqa: BLE001
                            if isinstance(retry_exc, RedmineApiError):
                                raise
                            failed_items.append(
                                build_failure_detail(
                                    item_id=item_id,
                                    action="update_retry_without_assignee",
                                    subject=subject,
                                    assigned_to_id=payload_assignee,
                                    issue_id=target_id,
                                    error=f"{exc} | retry_without_assignee_failed: {retry_exc}",
                                )
                            )
                            if not runtime.continue_on_child_error:
                                break
                            continue

                    failed_items.append(
                        build_failure_detail(
                            item_id=item_id,
                            action="update",
                            subject=subject,
                            assigned_to_id=payload_assignee,
                            issue_id=target_id,
                            error=str(exc),
                        )
                    )
                    if not runtime.continue_on_child_error:
                        break
                    continue

        try:
            child_res = client.create_issue(payload)
            issue_obj = safe_dict(child_res.get("issue"))
            child_issue_id = parse_int_or_none(issue_obj.get("id"))
            if child_issue_id is None:
                raise RuntimeError("Child creation response does not contain issue.id")
            created_children.append(
                {
                    "item_id": item_id,
                    "created_issue_id": child_issue_id,
                    "subject": subject,
                }
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, RedmineApiError):
                raise
            if "assigned_to_id" in payload and is_invalid_assignee_error(exc):
                retry_payload = dict(payload)
                retry_payload.pop("assigned_to_id", None)
                try:
                    child_res = client.create_issue(retry_payload)
                    issue_obj = safe_dict(child_res.get("issue"))
                    child_issue_id = parse_int_or_none(issue_obj.get("id"))
                    if child_issue_id is None:
                        raise RuntimeError("Child creation response does not contain issue.id")
                    created_children.append(
                        {
                            "item_id": item_id,
                            "created_issue_id": child_issue_id,
                            "subject": subject,
                        }
                    )
                    context.warnings.append(
                        f"{item_id}: retry success action=create_retry_without_assignee issue_id={child_issue_id} "
                        f"subject='{subject}' removed_assignee={payload_assignee}"
                    )
                    continue
                except Exception as retry_exc:  # noqa: BLE001
                    if isinstance(retry_exc, RedmineApiError):
                        raise
                    failed_items.append(
                        build_failure_detail(
                            item_id=item_id,
                            action="create_retry_without_assignee",
                            subject=subject,
                            assigned_to_id=payload_assignee,
                            issue_id=None,
                            error=f"{exc} | retry_without_assignee_failed: {retry_exc}",
                        )
                    )
                    if not runtime.continue_on_child_error:
                        break
                    continue

            failed_items.append(
                build_failure_detail(
                    item_id=item_id,
                    action="create",
                    subject=subject,
                    assigned_to_id=payload_assignee,
                    issue_id=None,
                    error=str(exc),
                )
            )
            if not runtime.continue_on_child_error:
                break

    apply_result = {
        "mode": "apply",
        "parent": {
            "created_issue_id": created_parent_issue_id,
            "updated_issue_id": updated_parent_issue_id,
            "effective_issue_id": parent_issue_id,
            "subject": parent_subject,
            "action": parent_action,
        },
        "children": created_children,
        "skipped_items": skipped_items,
        "failed_items": failed_items,
        "warnings": context.warnings,
        "unset_custom_fields": context.unset_custom_fields,
        "unresolved_mappings": context.unresolved_values,
    }
    safe_write_json(args.output, apply_result)

    if failed_items:
        raise RuntimeError("Some child issues failed to create. See output JSON for details.")

    print(f"Apply completed. Result written: {args.output}")
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except Exception as exc:  # noqa: BLE001
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
