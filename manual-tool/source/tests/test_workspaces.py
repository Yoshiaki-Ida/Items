from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

import manual_tool.app as app_module
from manual_tool.workspaces import WorkspaceStore


def test_workspace_lists_supported_files_and_ignores_tool_directories(tmp_path):
    root = tmp_path / "manuals"
    (root / "chapter").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "guide.md").write_text("# guide", encoding="utf-8")
    (root / "chapter" / "operation.html").write_text("<h1>operation</h1>", encoding="utf-8")
    (root / "memo.txt").write_text("memo", encoding="utf-8")
    (root / ".git" / "hidden.md").write_text("hidden", encoding="utf-8")

    workspace = WorkspaceStore().create(root)

    assert workspace.files() == ["guide.md"]


def test_workspace_ignores_files_in_child_folders(tmp_path):
    root = tmp_path / "manuals"
    (root / "chapter" / "deep").mkdir(parents=True)
    (root / "guide.md").write_text("# guide", encoding="utf-8")
    (root / "chapter" / "operation.html").write_text("<h1>operation</h1>", encoding="utf-8")
    (root / "chapter" / "deep" / "appendix.md").write_text("# appendix", encoding="utf-8")

    workspace = WorkspaceStore().create(root)

    assert workspace.files() == ["guide.md"]
    with pytest.raises(FileNotFoundError, match="対応する文書が見つかりません"):
        workspace.resolve_file("chapter/operation.html")
    with pytest.raises(FileNotFoundError, match="対応する文書が見つかりません"):
        workspace.resolve_file("chapter/deep/appendix.md")


def test_workspace_rejects_path_outside_root(tmp_path):
    root = tmp_path / "manuals"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    workspace = WorkspaceStore().create(root)

    with pytest.raises(ValueError, match="ワークスペース外"):
        workspace.resolve_file("../outside.md")


def test_pick_folder_and_open_direct_document(client, tmp_path, monkeypatch):
    root = tmp_path / "manuals"
    root.mkdir()
    (root / "operation.html").write_text("<h1>操作</h1><p>説明</p>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: root)

    picked = client.post("/api/workspaces/pick")
    workspace_id = picked.json()["workspace_id"]
    opened = client.post(
        f"/api/workspaces/{workspace_id}/documents/{quote('operation.html')}"
    )

    assert picked.status_code == 200
    assert picked.json()["files"] == ["operation.html"]
    assert opened.status_code == 200
    assert opened.json()["relative_path"] == "operation.html"
    assert "# 操作" in opened.json()["markdown"]


def test_export_writes_to_selected_folder_without_touching_source(client, tmp_path, monkeypatch):
    root = tmp_path / "manuals"
    root.mkdir()
    source = root / "guide.md"
    source.write_text("# 元文書", encoding="utf-8")
    destination = tmp_path / "export"
    destination.mkdir()
    selections = iter([root, destination])
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: next(selections))

    picked = client.post("/api/workspaces/pick").json()
    opened = client.post(
        f"/api/workspaces/{picked['workspace_id']}/documents/guide.md"
    ).json()
    updated = client.put(
        f"/api/documents/{opened['session_id']}",
        json={"markdown": "# 修正版"},
    ).json()
    ignored_id = updated["issues"][0]["id"]
    client.post(f"/api/documents/{opened['session_id']}/issues/{ignored_id}/ignore")
    exported = client.post(f"/api/documents/{opened['session_id']}/export")

    output = destination
    assert exported.status_code == 200
    assert (output / "guide_manual" / "guide_fixed.md").read_text(encoding="utf-8") == "# 修正版"
    assert (output / "guide.html").exists()
    assert (output / "guide_manual" / "lint-report.json").exists()
    report = json.loads((output / "guide_manual" / "lint-report.json").read_text(encoding="utf-8"))
    assert next(issue for issue in report if issue["id"] == ignored_id)["ignored"] is True
    assert not (output / "lint-report.json").exists()
    assert exported.json()["support_dir"] == str(output / "guide_manual")
    assert source.read_text(encoding="utf-8") == "# 元文書"
    assert not (app_module.store.root / opened["session_id"]).exists()


def test_export_places_images_below_selected_folder(client, tmp_path, monkeypatch):
    root = tmp_path / "manuals"
    image_dir = root / "images"
    image_dir.mkdir(parents=True)
    (image_dir / "figure.png").write_bytes(b"image")
    (root / "guide.html").write_text(
        '<h1>操作</h1><img src="images/figure.png" alt="図">', encoding="utf-8"
    )
    destination = tmp_path / "export"
    destination.mkdir()
    selections = iter([root, destination, destination])
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: next(selections))

    picked = client.post("/api/workspaces/pick").json()
    opened = client.post(
        f"/api/workspaces/{picked['workspace_id']}/documents/guide.html"
    ).json()
    session = app_module.store.get(opened["session_id"])
    (session.directory / "visio").mkdir()
    (session.directory / "visio" / "drawing.vsdx").write_bytes(b"visio")
    exported = client.post(f"/api/documents/{opened['session_id']}/export")

    assert exported.status_code == 200
    assert (destination / "guide.html").exists()
    assert (destination / "images" / "guide" / "figure.png").read_bytes() == b"image"
    assert 'src="images/guide/figure.png"' in (
        destination / "guide.html"
    ).read_text(encoding="utf-8")
    assert "../images/guide/figure.png" in (
        destination / "guide_manual" / "guide_fixed.md"
    ).read_text(encoding="utf-8")
    assert exported.json()["image_dir"] == str(destination / "images" / "guide")
    assert (destination / "visio" / "guide" / "drawing.vsdx").read_bytes() == b"visio"
    assert exported.json()["visio_dir"] == str(destination / "visio" / "guide")

    reopened_workspace = client.post("/api/workspaces/pick").json()
    reopened = client.post(
        f"/api/workspaces/{reopened_workspace['workspace_id']}/documents/guide.html"
    ).json()
    reopened_session = app_module.store.get(reopened["session_id"])
    assert (reopened_session.directory / "images" / "figure.png").read_bytes() == b"image"
    preview = client.post(
        f"/api/documents/{reopened['session_id']}/preview",
        json={"markdown": reopened["markdown"]},
    )
    assert f'/api/documents/{reopened["session_id"]}/assets/images/figure.png' in preview.text
