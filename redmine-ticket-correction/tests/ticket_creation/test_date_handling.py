import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_tools.ticket_creation import redmine_meeting_importer as mod


def make_data():
    return {
        "meeting": {"title": "定例会"},
        "meeting_summary": {},
        "redmine_meeting_fields": {},
        "summary": {},
        "human_review_required": [],
        "items": [
            {
                "id": "ITEM-001",
                "title": "A",
                "type": "action_item",
                "ticket_readiness": "ready",
                "redmine_issue_fields": {"期日": "今週中"},
            }
        ],
    }


def make_cfg():
    return {
        "redmine_url": "https://example.local/redmine",
        "verify_ssl": True,
        "timeout_seconds": 30,
    }


def test_due_date_relative_is_not_sent_and_iso_is_sent():
    config = {}
    ctx = mod.BuildContext(warnings=[], unresolved_values=[], unset_custom_fields=[])

    rel = mod.map_standard_field("期日", "今週中", config, ctx, "ITEM-1")
    assert rel is None

    iso = mod.map_standard_field("期日", "2026-07-31", config, ctx, "ITEM-1")
    assert iso == ("due_date", "2026-07-31")


def test_dry_run_has_placeholder_parent_id_and_no_http(tmp_path, monkeypatch):
    data = make_data()
    cfg = make_cfg()

    input_path = tmp_path / "in.json"
    cfg_path = tmp_path / "cfg.json"
    out_path = tmp_path / "out.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    called = {"http": 0}

    def fail_if_called(*args, **kwargs):
        called["http"] += 1
        raise AssertionError("HTTP must not be called in dry-run")

    monkeypatch.setattr(mod.RedmineClient, "request_json", fail_if_called)

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
            "--output",
            str(out_path),
        ]
    )

    assert code == 0
    assert called["http"] == 0

    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["mode"] == "dry-run"
    assert result["children"][0]["payload_template"]["parent_issue_id"] == "<created_parent_issue_id>"
