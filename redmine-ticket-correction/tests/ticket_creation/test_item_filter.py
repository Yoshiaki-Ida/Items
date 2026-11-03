import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_tools.ticket_creation import redmine_meeting_importer as mod


def make_data(item_count=2):
    items = []
    for i in range(item_count):
        idx = i + 1
        items.append(
            {
                "id": f"ITEM-{idx:03d}",
                "title": f"task-{idx}",
                "type": "action_item",
                "ticket_readiness": "ready",
                "redmine_issue_fields": {},
            }
        )
    return {
        "meeting": {"title": "定例会"},
        "meeting_summary": {},
        "redmine_meeting_fields": {},
        "summary": {},
        "human_review_required": [],
        "items": items,
    }


def make_cfg(tmp_path):
    cfg = {
        "redmine_url": "https://example.local/redmine",
        "verify_ssl": True,
        "timeout_seconds": 30,
        "continue_on_child_error": True,
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return cfg_path


def test_parent_create_api_called_first(tmp_path, monkeypatch):
    data = make_data(2)
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg_path = make_cfg(tmp_path)
    out_path = tmp_path / "out.json"

    call_order = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.n = 0

        def find_issues_by_subject(self, project_id, subject, limit=20):
            call_order.append("find")
            return []

        def create_issue(self, issue_payload):
            self.n += 1
            if self.n == 1:
                call_order.append("parent")
                return {"issue": {"id": 1000}}
            call_order.append("child")
            return {"issue": {"id": 2000 + self.n}}

    monkeypatch.setattr(mod, "RedmineClient", FakeClient)
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
    assert call_order[1] == "parent"


def test_parent_create_failure_stops_children(tmp_path, monkeypatch):
    data = make_data(2)
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg_path = make_cfg(tmp_path)
    out_path = tmp_path / "out.json"

    child_calls = {"count": 0}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def find_issues_by_subject(self, project_id, subject, limit=20):
            return []

        def create_issue(self, issue_payload):
            if issue_payload.get("parent_issue_id") is not None:
                child_calls["count"] += 1
            raise RuntimeError("parent create failed")

    monkeypatch.setattr(mod, "RedmineClient", FakeClient)
    monkeypatch.setenv("REDMINE_API_KEY", "dummy")
    monkeypatch.setattr(mod, "ask_duplicate_action", lambda *args, **kwargs: "create")

    with pytest.raises(RuntimeError):
        mod.run(
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

    assert child_calls["count"] == 0
    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["parent"]["created_issue_id"] is None


def test_multiple_children_share_same_parent_id(tmp_path, monkeypatch):
    data = make_data(3)
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg_path = make_cfg(tmp_path)
    out_path = tmp_path / "out.json"

    child_parent_ids = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.n = 0

        def find_issues_by_subject(self, project_id, subject, limit=20):
            return []

        def create_issue(self, issue_payload):
            self.n += 1
            if self.n == 1:
                return {"issue": {"id": 24680}}
            child_parent_ids.append(issue_payload.get("parent_issue_id"))
            return {"issue": {"id": 30000 + self.n}}

    monkeypatch.setattr(mod, "RedmineClient", FakeClient)
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
    assert child_parent_ids == [24680, 24680, 24680]


def test_invalid_assignee_retries_without_assigned_to_id(tmp_path, monkeypatch):
    data = make_data(1)
    data["items"][0]["redmine_issue_fields"] = {"担当者": "I田"}
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg = {
        "redmine_url": "https://example.local/redmine",
        "verify_ssl": True,
        "timeout_seconds": 30,
        "user_ids": {"I田": 123},
        "continue_on_child_error": True,
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "out.json"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.n = 0

        def find_issues_by_subject(self, project_id, subject, limit=20):
            return []

        def create_issue(self, issue_payload):
            self.n += 1
            if self.n == 1:
                return {"issue": {"id": 24680}}
            if self.n == 2:
                raise RuntimeError("HTTP 422 POST /issues.json body={\"errors\":[\"担当者 は不正な値です\"]}")
            assert "assigned_to_id" not in issue_payload
            return {"issue": {"id": 24681}}

    monkeypatch.setattr(mod, "RedmineClient", FakeClient)
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
    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["failed_items"] == []
    assert len(result["children"]) == 1
    assert any("create_retry_without_assignee" in w for w in result["warnings"])


def test_duplicate_child_subject_skip_when_both_no(tmp_path, monkeypatch):
    data = make_data(1)
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg_path = make_cfg(tmp_path)
    out_path = tmp_path / "out.json"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.n = 0

        def find_issues_by_subject(self, project_id, subject, limit=20):
            if "議事録" in subject:
                return []
            return [{"id": 999, "subject": subject}]

        def create_issue(self, issue_payload):
            self.n += 1
            if self.n == 1:
                return {"issue": {"id": 24680}}
            raise AssertionError("child create should be skipped")

        def update_issue(self, issue_id, issue_payload):
            raise AssertionError("child update should be skipped")

    monkeypatch.setattr(mod, "RedmineClient", FakeClient)
    monkeypatch.setenv("REDMINE_API_KEY", "dummy")
    monkeypatch.setattr(mod, "ask_duplicate_action", lambda *args, **kwargs: "skip")

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
    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["children"] == []
    assert result["skipped_items"][0]["item_id"] == "ITEM-001"
    assert result["skipped_items"][0]["reason"] == "duplicate_subject_skip"


def test_duplicate_child_update_retries_without_assigned_to_id(tmp_path, monkeypatch):
    data = make_data(1)
    data["items"][0]["redmine_issue_fields"] = {"担当者": "I田"}
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg = {
        "redmine_url": "https://example.local/redmine",
        "verify_ssl": True,
        "timeout_seconds": 30,
        "user_ids": {"I田": 123},
        "continue_on_child_error": True,
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "out.json"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.update_calls = 0

        def find_issues_by_subject(self, project_id, subject, limit=20):
            if "議事録" in subject:
                return []
            return [{"id": 616657, "subject": subject}]

        def create_issue(self, issue_payload):
            return {"issue": {"id": 616656}}

        def update_issue(self, issue_id, issue_payload):
            self.update_calls += 1
            if issue_payload.get("parent_issue_id") is None:
                return {"ok": True}
            if self.update_calls == 1:
                raise RuntimeError("HTTP 422 PUT /issues/616657.json body={\"errors\":[\"担当者 は不正な値です\"]}")
            assert "assigned_to_id" not in issue_payload
            return {"ok": True}

    monkeypatch.setattr(mod, "RedmineClient", FakeClient)
    monkeypatch.setenv("REDMINE_API_KEY", "dummy")
    monkeypatch.setattr(mod, "ask_duplicate_action", lambda *args, **kwargs: "update")

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
    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["failed_items"] == []
    assert len(result["children"]) == 1
    assert result["children"][0]["updated_issue_id"] == 616657
    assert any("update_retry_without_assignee" in w for w in result["warnings"])
