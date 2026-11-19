from __future__ import annotations

import manual_tool.app as app_module
from manual_tool.assembly.schema import load_manual


def create_source(tmp_path):
    project = tmp_path / "manual_project"
    source = project / "source"
    source.mkdir(parents=True)
    (source / "overview.html").write_text("<html><body><h1>概要</h1><p>本文</p></body></html>", encoding="utf-8")
    (source / "setup.html").write_text("<html><body><h1>セットアップ</h1></body></html>", encoding="utf-8")
    nested = source / "nested"
    nested.mkdir()
    (nested / "appendix.html").write_text("<html><body><h1>付録</h1></body></html>", encoding="utf-8")
    return project, source


def definition_payload():
    return {
        "title": "製品マニュアル",
        "output": "output/manual.html",
        "chapters": [
            {"id": "overview", "title": "概要", "file": "overview.html"},
            {"id": "setup", "title": "セットアップ", "file": "setup.html"},
        ],
    }


def test_editor_picks_html_folder_and_previews_source(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    (source / "overview.html").write_text(
        "<html><body><h1>概要</h1><h2>詳細</h2><p>本文</p></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)

    picked = client.post("/api/manual-editor/pick-source")
    project_id = picked.json()["project_id"]
    preview = client.get(f"/api/manual-editor/{project_id}/preview/overview.html")

    assert picked.status_code == 200
    assert [item["file"] for item in picked.json()["sources"]] == ["overview.html", "setup.html"]
    assert picked.json()["sources"][0]["direct_heading_count"] == 1
    assert preview.status_code == 200
    assert "概要" in preview.text
    assert "<base href=" in preview.text


def test_editor_saves_and_reloads_yaml(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    yaml_path = source / "manual.yaml"
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)
    project_id = client.post("/api/manual-editor/pick-source").json()["project_id"]

    saved = client.post(f"/api/manual-editor/{project_id}/save", json=definition_payload())
    loaded = client.post("/api/manual-editor/pick-source")

    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert "source_dir: ." in yaml_path.read_text(encoding="utf-8")
    assert loaded.status_code == 200
    assert loaded.json()["yaml_path"] == str(yaml_path)
    assert loaded.json()["definition"]["manual"]["title"] == "製品マニュアル"
    assert len(loaded.json()["definition"]["chapters"]) == 2


def test_editor_creates_standard_project_from_parent_folder(client, tmp_path, monkeypatch):
    project, source = create_source(tmp_path)
    yaml_path = project / "manual.yaml"
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: project)

    picked = client.post("/api/manual-editor/pick-source")
    project_id = picked.json()["project_id"]
    saved = client.post(f"/api/manual-editor/{project_id}/save", json=definition_payload())
    built = client.post(f"/api/manual-editor/{project_id}/build")

    assert picked.status_code == 200
    assert picked.json()["source_path"] == str(source)
    assert picked.json()["yaml_path"] is None
    assert [item["file"] for item in picked.json()["sources"]] == ["overview.html", "setup.html"]
    assert saved.status_code == 200
    assert saved.json()["yaml_path"] == str(yaml_path)
    assert load_manual(yaml_path).source_dir == "source"
    assert built.status_code == 200
    assert built.json()["output_path"] == str(project / "output" / "manual.html")


def test_editor_preserves_stable_ids_when_saving_reordered_chapters(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    (source / "overview.html").write_text(
        '<html><body><h1>概要</h1><p><a data-ref="setup"></a></p></body></html>',
        encoding="utf-8",
    )
    yaml_path = source / "manual.yaml"
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)
    project_id = client.post("/api/manual-editor/pick-source").json()["project_id"]
    payload = definition_payload()
    payload["chapters"] = list(reversed(payload["chapters"]))

    saved = client.post(f"/api/manual-editor/{project_id}/save", json=payload)
    built = client.post(f"/api/manual-editor/{project_id}/build")

    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert [node.id for node in load_manual(yaml_path).chapters] == ["setup", "overview"]
    assert built.status_code == 200
    assert built.json()["success"] is True
    output = source / "output" / "manual.html"
    assert '<a data-ref="setup" href="#setup">1. セットアップ</a>' in output.read_text(encoding="utf-8")


def test_editor_generates_valid_unique_ids_only_when_needed(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    yaml_path = source / "manual.yaml"
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)
    project_id = client.post("/api/manual-editor/pick-source").json()["project_id"]
    payload = definition_payload()
    payload["chapters"][0]["id"] = "invalid id"
    payload["chapters"][1]["id"] = "invalid id"

    saved = client.post(f"/api/manual-editor/{project_id}/save", json=payload)

    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert [node.id for node in load_manual(yaml_path).chapters] == ["overview", "setup"]


def test_editor_starts_with_empty_structure_when_manual_yaml_is_absent(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)

    picked = client.post("/api/manual-editor/pick-source")

    assert picked.status_code == 200
    assert picked.json()["yaml_path"] is None
    assert picked.json()["definition"] is None


def test_editor_returns_structure_errors_without_saving(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    yaml_path = source / "manual.yaml"
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)
    project_id = client.post("/api/manual-editor/pick-source").json()["project_id"]
    payload = definition_payload()
    payload["chapters"][1]["file"] = "overview.html"

    response = client.post(f"/api/manual-editor/{project_id}/save", json=payload)

    assert response.status_code == 200
    assert response.json()["saved"] is False
    assert "duplicate-file" in {issue["code"] for issue in response.json()["issues"]}
    assert not yaml_path.exists()


def test_editor_builds_its_saved_yaml_without_selecting_it_again(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    yaml_path = source / "manual.yaml"
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)
    project_id = client.post("/api/manual-editor/pick-source").json()["project_id"]
    client.post(f"/api/manual-editor/{project_id}/save", json=definition_payload())

    response = client.post(f"/api/manual-editor/{project_id}/build")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["heading_count"] == 2
    output = source / "output" / "manual.html"
    assert output.exists()
    assert "1. 概要" in output.read_text(encoding="utf-8")


def test_editor_requires_yaml_save_before_build(client, tmp_path, monkeypatch):
    _, source = create_source(tmp_path)
    monkeypatch.setattr(app_module, "_pick_directory", lambda _title: source)
    project_id = client.post("/api/manual-editor/pick-source").json()["project_id"]

    response = client.post(f"/api/manual-editor/{project_id}/build")

    assert response.status_code == 409
    assert "YAMLへ保存" in response.json()["detail"]
