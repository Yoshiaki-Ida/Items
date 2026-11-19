from __future__ import annotations

from manual_tool.assembly.schema import ManualDefinition, ManualNode, load_manual, save_manual


def test_yaml_save_and_reload_round_trip(tmp_path):
    definition = ManualDefinition(
        title="製品マニュアル",
        chapters=[
            ManualNode("overview", "概要", "overview.html", numbered=False),
            ManualNode(
                "operation",
                "基本操作",
                children=[ManualNode("startup", "起動", "startup.html")],
            ),
        ],
    )
    path = tmp_path / "manual.yaml"

    save_manual(path, definition)
    loaded = load_manual(path)

    assert loaded == definition
    assert "1 概要" not in path.read_text(encoding="utf-8")
    assert "numbered: false" in path.read_text(encoding="utf-8")
    assert "id: startup" in path.read_text(encoding="utf-8")


def test_invalid_yaml_shape_is_rejected(tmp_path):
    path = tmp_path / "manual.yaml"
    path.write_text("chapters: invalid", encoding="utf-8")

    try:
        load_manual(path)
    except ValueError as exc:
        assert "manual設定" in str(exc)
    else:
        raise AssertionError("Invalid YAML shape was accepted")
