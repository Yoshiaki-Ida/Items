import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_tools.ticket_creation import redmine_meeting_importer as mod


def test_registered_user_key_missing_from_process_requests_full_restart(monkeypatch):
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)
    monkeypatch.setattr(mod, "_get_windows_user_environment_variable", lambda name: "user-key")

    with pytest.raises(RuntimeError, match="プロセスへ反映されていません") as exc_info:
        mod.require_redmine_api_key()

    message = str(exc_info.value)
    assert "VS Code/Copilot本体を完全に終了して再起動" in message
    assert "再登録" in message
    assert "offline／ローカル処理への切替" in message
    assert "user-key" not in message


def test_stale_process_key_reports_mismatch_without_exposing_keys(monkeypatch):
    monkeypatch.setenv("REDMINE_API_KEY", "old-process-key")
    monkeypatch.setattr(mod, "_get_windows_user_environment_variable", lambda name: "new-user-key")

    with pytest.raises(RuntimeError, match="古いREDMINE_API_KEY") as exc_info:
        mod.require_redmine_api_key()

    message = str(exc_info.value)
    assert "old-process-key" not in message
    assert "new-user-key" not in message
    assert "Checkpoint Redoだけでは更新されません" in message


def test_matching_process_and_user_key_is_accepted(monkeypatch):
    monkeypatch.setenv("REDMINE_API_KEY", "same-key")
    monkeypatch.setattr(mod, "_get_windows_user_environment_variable", lambda name: "same-key")

    assert mod.require_redmine_api_key() == "same-key"


def test_missing_key_message_contains_one_time_registration_guidance(monkeypatch):
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)
    monkeypatch.setattr(mod, "_get_windows_user_environment_variable", lambda name: "")

    with pytest.raises(RuntimeError, match="登録されていません") as exc_info:
        mod.require_redmine_api_key()

    message = str(exc_info.value)
    assert "SetEnvironmentVariable" in message
    assert "チャットやコマンド引数" in message


def test_http_401_message_explains_stale_host_process():
    message = mod._redmine_http_error_message(401, "GET", "https://redmine.example/issues.json", "")

    assert "認証に失敗しました" in message
    assert "Checkpoint Redoだけでは更新されません" in message
    assert "offline／ローカルデータ" in message


def test_http_403_message_distinguishes_authorization():
    message = mod._redmine_http_error_message(403, "GET", "https://redmine.example/issues.json", "")

    assert "認可に失敗しました" in message
    assert "権限" in message
