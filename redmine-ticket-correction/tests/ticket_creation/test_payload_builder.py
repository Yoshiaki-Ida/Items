import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_tools.ticket_creation import redmine_meeting_importer as mod


def make_sample_data():
    return {
        "meeting": {"title": "定例会"},
        "meeting_summary": {"overview": "概要"},
        "redmine_meeting_fields": {"開催回数": 11},
        "summary": {},
        "human_review_required": [],
        "items": [
            {
                "id": "ITEM-001",
                "title": "対応1",
                "type": "action_item",
                "ticket_readiness": "ready",
                "redmine_issue_fields": {},
            }
        ],
    }


def make_cfg():
    return {
        "redmine_url": "https://example.local/redmine",
        "verify_ssl": True,
        "timeout_seconds": 30,
        "parent_subject_prefix": "",
        "parent_subject_suffix": " 議事録",
        "custom_field_ids": {"開催回数": 101},
    }


def test_parent_payload_generated_correctly():
    data = make_sample_data()
    cfg = make_cfg()
    runtime = mod.make_runtime_settings(cfg)
    formatter = mod.TextFormatter(runtime.formatter)
    ctx = mod.BuildContext(warnings=[], unresolved_values=[], unset_custom_fields=[])

    subject = mod.make_parent_subject(data, runtime)
    payload = mod.build_parent_issue_payload(
        data,
        cfg,
        formatter,
        ctx,
        project_id="automation_test_project",
        parent_tracker_id=6,
        parent_subject=subject,
    )

    assert payload["project_id"] == "automation_test_project"
    assert payload["tracker_id"] == 6
    assert payload["subject"] == "定例会 議事録"
    assert payload["custom_fields"] == [{"id": 101, "value": 11}]


def test_parent_response_id_used_for_children(tmp_path, monkeypatch):
    data = make_sample_data()
    cfg = make_cfg()

    input_path = tmp_path / "in.json"
    cfg_path = tmp_path / "cfg.json"
    out_path = tmp_path / "out.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.created_payloads = []

        def find_issues_by_subject(self, project_id, subject, limit=20):
            return []

        def create_issue(self, issue_payload):
            self.created_payloads.append(issue_payload)
            if len(self.created_payloads) == 1:
                return {"issue": {"id": 24680}}
            return {"issue": {"id": 24681}}

    fake_client = FakeClient()
    monkeypatch.setattr(mod, "RedmineClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setenv("REDMINE_API_KEY", "dummy")
    monkeypatch.setattr(mod, "ask_duplicate_action", lambda *args, **kwargs: "create")

    code = mod.run(
        [
            str(input_path),
            "--config",
            str(cfg_path),
            "--project-id",
            "42",
            "--parent-tracker-id",
            "6",
            "--child-tracker-id",
            "7",
            "--apply",
            "--confirm-create-parent",
            "--output",
            str(out_path),
        ]
    )

    assert code == 0
    assert fake_client.created_payloads[0]["tracker_id"] == 6
    assert fake_client.created_payloads[1]["parent_issue_id"] == 24680


def test_child_description_schema_v16_excludes_non_standard_fields():
    item = {
        "id": "ITEM-001",
        "type": "action_item",
        "ticket_readiness": "ready",
        "description": "本文",
        "rationale": "理由",
        "expected_state": "期待状態",
        "action_plan": "対応方針は本文に入れない",
        "completion_criteria": ["確認条件は本文に入れない"],
        "next_review_timing": "次回確認は本文に入れない",
        "source_grounding": {"support_level": "explicit"},
    }
    text = mod.build_item_description(item, mod.TextFormatter("markdown"))

    assert "本文" in text
    assert "理由・背景:" in text
    assert "期待状態:" in text
    assert "対応方針" not in text
    assert "確認条件" not in text
    assert "ITEM ID" not in text
    assert "action_item" not in text
    assert "ready" not in text
    assert "explicit" not in text


def test_child_custom_fields_mapping_schema_v16_only_specific_keys():
    item = {
        "id": "ITEM-001",
        "title": "t",
        "description": "d",
        "redmine_issue_fields": {
            "処置内容": "処置A",
            "確認内容": "確認A",
            "確認日": None,
            "開発項目": "子チケットでは送らない",
        },
    }
    config = {
        "custom_field_ids": {
            "処置内容": 201,
            "確認内容": 202,
            "確認日": 203,
            "指摘日": 18,
            "開発項目": 999,
        }
    }
    ctx = mod.BuildContext(warnings=[], unresolved_values=[], unset_custom_fields=[])
    payload = mod.build_child_issue_payload(
        item,
        config,
        mod.TextFormatter("markdown"),
        ctx,
        project_id="42",
        parent_issue_id=100,
        child_tracker_id=7,
        run_date=date(2026, 7, 16),
    )

    custom_fields = payload.get("custom_fields", [])
    assert {"id": 201, "value": "処置A"} in custom_fields
    assert {"id": 202, "value": "確認A"} in custom_fields
    assert all(x.get("id") != 203 for x in custom_fields)
    assert {"id": 18, "value": "2026-07-16"} in custom_fields
    assert all(x.get("id") != 999 for x in custom_fields)


def test_child_confirm_date_unreadable_gets_provisional_date():
    item = {
        "id": "ITEM-009",
        "title": "t",
        "description": "d",
        "redmine_issue_fields": {
            "確認日": "来週",
        },
    }
    config = {
        "custom_field_ids": {
            "確認日": 203,
            "指摘日": 18,
        }
    }
    ctx = mod.BuildContext(warnings=[], unresolved_values=[], unset_custom_fields=[])
    payload = mod.build_child_issue_payload(
        item,
        config,
        mod.TextFormatter("markdown"),
        ctx,
        project_id="42",
        parent_issue_id=100,
        child_tracker_id=7,
        run_date=date(2026, 7, 16),
    )

    custom_fields = payload.get("custom_fields", [])
    assert {"id": 203, "value": "2026-07-23"} in custom_fields
    assert {"id": 18, "value": "2026-07-16"} in custom_fields
    assert any(x.get("reason") == "invalid_date_format" for x in ctx.unresolved_values)
    assert any("暫定値を設定" in w for w in ctx.warnings)


def test_assignee_mapping_falls_back_to_surname_key():
    ctx = mod.BuildContext(warnings=[], unresolved_values=[], unset_custom_fields=[])
    cfg = {"user_ids": {"田中": 1783}}

    mapped = mod.map_standard_field("担当者", "田中 太郎", cfg, ctx, "ITEM-001")

    assert mapped == ("assigned_to_id", 1783)
    assert ctx.unresolved_values == []
