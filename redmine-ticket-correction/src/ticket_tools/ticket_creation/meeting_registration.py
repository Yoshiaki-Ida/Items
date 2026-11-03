"""Read-only registration candidates and payload-derived HTML preview."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


def optional_text(value):
    return "" if value is None else str(value).strip()


def evidence_paragraph(rows):
    """Keep only supplied evidence; never infer speaker identity or time."""
    if not isinstance(rows, list):
        return ""
    rendered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parts = [optional_text(row.get(k)) for k in ("timestamp", "speaker", "summary")]
        line = " / ".join(p for p in parts if p)
        if line and line not in rendered:
            rendered.append(line)
    return "根拠：" + "；".join(rendered) if rendered else ""


def separate_evidence(rationale, evidence):
    parts = re.split(r"(?m)(?:^|(?<=[\s。.!?！？]))根拠[：:]\s*", rationale)
    if len(parts) == 1:
        return rationale, evidence
    entries = [part.strip() for part in parts[1:]]
    if evidence:
        entries.append(evidence.removeprefix("根拠："))
    entries = list(dict.fromkeys(entry for entry in entries if entry))
    return parts[0].rstrip(), "根拠：" + "\n".join(entries) if entries else ""


def display_url(value):
    parts = urlsplit(value)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Redmine URL must not contain credentials, query or fragment")
    return urlunsplit(parts).rstrip("/")


def paged_projects(client):
    rows, seen, offset = [], set(), 0
    while True:
        result = client.request_json("GET", "/projects.json", {"limit": 100, "offset": offset})
        page = result.get("projects")
        if not isinstance(page, list) or not isinstance(result.get("total_count"), int):
            raise ValueError("Invalid projects response")
        for row in page:
            if not isinstance(row, dict) or not isinstance(row.get("id"), int) or row["id"] in seen:
                raise ValueError("Invalid or repeated project page")
            seen.add(row["id"])
            rows.append({k: row[k] for k in ("id", "name", "identifier", "parent") if k in row})
        offset += len(page)
        if offset >= result["total_count"]:
            return rows
        if not page:
            raise ValueError("Incomplete project pagination")


def exact_choice(rows, name, identifier=None):
    matches = [r for r in rows if (name is None or r.get("name") == name)
               and (identifier is None or str(r.get("id")) == str(identifier) or r.get("identifier") == identifier)]
    if len(matches) != 1:
        raise ValueError("Selection must match exactly one candidate; select an ID to disambiguate")
    return matches[0]


def registration_candidates(client, base_url, project_name=None, project_id=None,
                            parent_tracker_name=None, child_tracker_name=None):
    projects = paged_projects(client)
    result = {"redmine_url": display_url(base_url), "projects": projects,
              "note": "参照権限で取得したプロジェクトと有効トラッカー。登録権限や必須項目充足は保証しません。"}
    if project_name is None and project_id is None:
        if parent_tracker_name or child_tracker_name:
            raise ValueError("Select a project first")
        return result
    project = exact_choice(projects, project_name, project_id)
    detail = client.request_json("GET", f"/projects/{quote(str(project['id']), safe='')}.json", {"include": "trackers"}).get("project", {})
    trackers = detail.get("trackers")
    if detail.get("id") != project["id"] or not isinstance(trackers, list):
        raise ValueError("Project trackers unavailable")
    if any(not isinstance(t, dict) or not isinstance(t.get("id"), int) or not isinstance(t.get("name"), str) for t in trackers):
        raise ValueError("Invalid trackers response")
    result.update(project=project, trackers=[{"id": t["id"], "name": t["name"]} for t in trackers])
    if parent_tracker_name is not None:
        result["parent_tracker"] = exact_choice(result["trackers"], parent_tracker_name)
    if child_tracker_name is not None:
        result["child_tracker"] = exact_choice(result["trackers"], child_tracker_name)
    return result


def load_labels(path, base_url, project_id, parent_id, child_id):
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    project = data.get("project", {})
    if data.get("redmine_url") != display_url(base_url) or str(project_id) not in {str(project.get("id")), project.get("identifier")}:
        raise ValueError("Registration candidates do not match destination")
    for key, expected in (("parent_tracker", parent_id), ("child_tracker", child_id)):
        selected = data.get(key, {})
        if selected.get("id") != expected or selected not in data.get("trackers", []):
            raise ValueError("Registration candidates do not match tracker IDs")
    return data


def render_registration_preview(result, base_url, labels, config):
    """Render exact planned payload text, without executing or rewriting it."""
    esc = lambda v: html.escape(optional_text(v), quote=True)
    parent = result["parent"]["payload"]
    rows = [("親チケット", parent)] + [("子チケット " + str(c["item_id"]), c["payload_template"]) for c in result["children"]]
    articles = []
    for kind, payload in rows:
        key = "parent_tracker" if payload is parent else "child_tracker"
        project = labels.get("project", {})
        tracker = labels.get(key, {})
        assignee = payload.get("assigned_to_id")
        user_ids = config.get("user_ids") or {}
        names = [str(n) for n, i in user_ids.items() if str(i) == str(assignee)] if assignee is not None else []
        fields = {"プロジェクト": f"{project.get('name', '名称未取得')} (ID/識別子: {payload.get('project_id')})",
                  "トラッカー": f"{tracker.get('name', '名称未取得')} (ID: {payload.get('tracker_id')})",
                  "担当者（設定の対応表）": ' / '.join(names) + f" (ID: {assignee})" if assignee is not None else "未指定",
                  "期限": payload.get("due_date") or "未指定"}
        table = ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k,v in fields.items())
        articles.append(f'<article><h2>{esc(kind)}：{esc(payload.get("subject"))}</h2><dl>{table}</dl><h3>登録予定の本文</h3><pre>{esc(payload.get("description"))}</pre><details><summary>登録予定フィールド全体</summary><pre>{esc(json.dumps(payload,ensure_ascii=False,indent=2))}</pre></details></article>')
    diagnostics = {k: result.get(k, []) for k in ("warnings", "skipped_items", "unset_custom_fields", "unresolved_mappings")}
    return ('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>Redmine登録ドラフト</title><style>body{font-family:system-ui;max-width:1000px;margin:auto;padding:20px}article{border:1px solid #bbb;padding:16px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}dd{margin-bottom:8px}dt{font-weight:bold}</style>'
            '<h1>登録ドラフト（dry-run）</h1><p><strong>まだRedmineには登録されていません。</strong></p>'
            f'<p>接続先：{esc(display_url(base_url))} ／ 親1件・子{len(result["children"])}件</p>'
            '<p>名称は候補取得・設定時点の情報です。議事録HTMLとは別に、最終本文・登録先・担当者・期限を確認してください。</p>'
            + ''.join(articles) + '<h2>設定不足・警告・対象外</h2><pre>' + esc(json.dumps(diagnostics,ensure_ascii=False,indent=2))
            + '</pre><p>設定不足を解消し、確認後の新しいメッセージで「Redmineへ登録して」と依頼してください。入力や設定を変更した場合は再ドラフト・再承認が必要です。</p></html>')


def main(argv=None):
    from .redmine_meeting_importer import load_config, make_runtime_settings, RedmineClient, require_redmine_api_key, safe_write_json
    parser = argparse.ArgumentParser(description="Read Redmine project / enabled tracker candidates (GET only)")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project-name")
    parser.add_argument("--project-id")
    parser.add_argument("--parent-tracker-name")
    parser.add_argument("--child-tracker-name")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    runtime = make_runtime_settings(load_config(args.config))
    display_url(runtime.redmine_url)
    client = RedmineClient(runtime.redmine_url, require_redmine_api_key(), runtime.verify_ssl,
                           runtime.timeout_seconds, runtime.ca_bundle, runtime.proxy)
    result = registration_candidates(client, runtime.redmine_url, args.project_name, args.project_id,
                                     args.parent_tracker_name, args.child_tracker_name)
    safe_write_json(args.output, result)
    print("候補取得完了（登録は行っていません）: " + args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
