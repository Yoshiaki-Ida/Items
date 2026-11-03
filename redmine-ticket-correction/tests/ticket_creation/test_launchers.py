import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["run_meeting_importer.bat", "export_tickets.bat", "create_children_from_markdown.bat"])
def test_launchers_are_portable_and_keep_secrets_out_of_arguments(name):
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert '%PROJECT_ROOT%\\.venv\\Scripts\\python.exe' in text
    assert "WORKSPACE_ROOT" not in text
    assert "--insecure" not in text
    assert "--api-key" not in text
    assert "Read-Host" not in text


@pytest.mark.skipif(os.name != "nt", reason="Windows launchers")
@pytest.mark.parametrize("name, expected", [("run_meeting_importer.bat", 2), ("export_tickets.bat", 0), ("create_children_from_markdown.bat", 2)])
def test_launchers_show_usage_without_network(name, expected):
    result = subprocess.run(
        ["cmd", "/c", str(ROOT / "scripts" / name), "--help"],
        capture_output=True, timeout=20,
    )
    assert result.returncode == expected, result.stdout
    assert b"Usage:" in result.stdout