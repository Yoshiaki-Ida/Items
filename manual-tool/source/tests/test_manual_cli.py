from __future__ import annotations

from manual_tool.assembly.cli import main
from manual_tool.assembly.schema import ManualDefinition, ManualNode, save_manual


def test_build_cli_runs_without_gui(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "overview.html").write_text("<h1>概要</h1>", encoding="utf-8")
    yaml_path = tmp_path / "manual.yaml"
    save_manual(yaml_path, ManualDefinition("Manual", chapters=[ManualNode("overview", "概要", "overview.html")]))

    exit_code = main([str(yaml_path)])

    assert exit_code == 0
    assert (tmp_path / "output" / "manual.html").exists()


def test_build_cli_returns_error_for_invalid_manual(tmp_path):
    yaml_path = tmp_path / "manual.yaml"
    save_manual(yaml_path, ManualDefinition("Manual", chapters=[ManualNode("missing", "Missing", "missing.html")]))

    assert main([str(yaml_path)]) == 2
