from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

import manual_tool.app as app_module


def test_index_uses_folder_based_document_opening(client):
    response = client.get("/")

    assert response.status_code == 200
    assert 'id="openFolder"' in response.text
    assert 'id="fileInput"' not in response.text
    assert 'id="dropzone"' not in response.text
    assert "ファイルを直接開く" not in response.text
    assert 'id="exportButton"' in response.text
    assert "HTMLをフォルダへ書出し" in response.text
    assert 'id="previewButton"' not in response.text
    assert 'id="download"' not in response.text
    assert "別フォルダへ書き出し" not in response.text
    assert 'id="chooseComposition"' in response.text
    assert 'id="chooseDocumentEditor"' in response.text
    assert 'id="buildManualYaml"' in response.text
    assert 'id="loadManualYaml"' not in response.text
    assert 'id="buildScreen"' not in response.text
    assert 'id="manualStructure"' in response.text
    assert "HTML一覧" in response.text
    assert "マニュアル構成にないHTMLは追加できます。" in response.text
    assert 'data-panel="editPanel">元データ</button>' in response.text
    assert 'data-panel="visualEditPanel">編集ビュー</button>' in response.text
    assert 'id="visualEditor"' in response.text
    assert 'id="elementProperties"' in response.text

    page = BeautifulSoup(response.text, "html.parser")
    main_modes = [button.get("id") for button in page.select(".mode-cards > .mode-card")]
    assert main_modes == ["chooseComposition", "chooseDocumentEditor"]
    assert page.select_one("#compositionScreen #compositionBuildResult") is not None
    assert [item.get_text(strip=True) for item in page.select(".structure-columns > *")] == [
        "採番",
        "構成番号",
        "HTML名",
    ]


def test_ui_assets_are_not_cached(client):
    index = client.get("/")
    script = client.get("/static/app.js?v=test")

    assert index.headers["cache-control"] == "no-store, max-age=0"
    assert script.headers["cache-control"] == "no-store, max-age=0"
    assert "/static/app.js?v=" in index.text


def test_preview_and_editor_share_layout_with_persistent_issues(client):
    response = client.get("/")

    split = BeautifulSoup(response.text, "html.parser").select_one(".split")
    assert split.select_one("#editPanel") is not None
    assert split.select_one("#previewPanel") is not None
    assert split.select_one("#preview[sandbox='allow-same-origin']") is not None
    assert split.select_one("#visualEditor[sandbox='allow-same-origin']") is not None
    assert split.select_one("#elementProperties #elementText") is not None
    assert split.select_one("#elementProperties #replacementImage") is not None
    assert split.select_one("#elementProperties #saveVisualHtml") is not None
    assert split.select_one("#previewProgress[role='status'] progress") is not None
    assert split.select_one("#previewProgressText") is not None
    assert split.select_one("#paneResizer[role='separator']") is not None
    assert split.select_one(".issues-panel") is not None
    document_progress = BeautifulSoup(response.text, "html.parser").select_one("#documentProgress[role='status']")
    assert document_progress.select_one("progress") is not None
    assert document_progress.select_one("#documentProgressText") is not None

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert 'resizer.addEventListener("pointerdown"' in script.text
    assert 'localStorage.setItem(storageKey' in script.text
    assert "先にグループ項目を追加してください" not in script.text
    assert "createCompositionNode" in script.text
    assert 'class="structure-numbered"' in script.text
    assert 'class="structure-name"' in script.text
    assert 'name.title = node.file || "グループ項目"' in script.text
    assert "source?.direct_heading_count || 0" in script.text
    assert "numbered.onclick = event => event.stopPropagation()" in script.text
    assert "node.numbered = numbered.checked" in script.text
    assert "syncCompositionNumberingFromInputs" in script.text
    assert "syncCompositionNumberingFromInputs();" in script.text
    assert 'node.numbered !== false ? `${number.join(".")}.` : "-"' in script.text
    assert "refreshPreview(payload.session_id, payload.markdown);" in script.text
    assert "function startPreviewProgress()" in script.text
    assert 'function finishPreviewProgress(token, completed, errorMessage = "")' in script.text
    assert "state.preview.timer = setInterval(updateElapsed, 100);" in script.text
    assert "function discardPendingPreviewFrames()" in script.text
    assert "function stagePreviewFrame(preview, token, sessionId)" in script.text
    assert 'frame.addEventListener("load", () =>' in script.text
    assert 'current.insertAdjacentElement("afterend", frame);' in script.text
    assert 'if (token !== state.preview.token || state.activeId !== sessionId) return;' in script.text
    assert 'if (!preview.trim()) throw new Error(' in script.text
    assert 'requestAnimationFrame(() => requestAnimationFrame(() =>' in script.text
    assert "finishPreviewProgress(token, true);" in script.text
    assert "finishPreviewProgress(token, false, error.message);" in script.text
    assert "プレビューを表示できません:" in script.text
    assert "const existing = state.workspaceSessions.get(relativePath);" in script.text
    assert "state.documents.has(existing)" in script.text
    assert "state.openingWorkspaceFiles.size" in script.text
    assert "state.openingWorkspaceFiles.delete(relativePath)" in script.text
    assert "function startDocumentProgress(label)" in script.text
    assert "function finishDocumentProgress(token, completed, message" in script.text
    assert "state.documentLoad.timer = setInterval(updateElapsed, 100);" in script.text
    assert "function closeDocument(id)" in script.text
    assert "closeDocument(item.session_id);" in script.text
    assert "async function flushActiveDocument()" in script.text
    assert "clearTimeout(state.saveTimer);" in script.text
    assert "const document = await flushActiveDocument();" in script.text
    assert "function selectVisualElement(target)" in script.text
    assert "function splitHeadingNumber(text)" in script.text
    assert "async function applyVisualChange()" in script.text
    assert "async function saveVisualHtml(showMessage = true)" in script.text
    assert "/visual-edit" in script.text
    assert "function synchronizeFromEditor()" in script.text
    assert "function synchronizeFromFrame(frame)" in script.text
    assert "function bindPreviewSelection(frame)" in script.text
    assert "function goToIssue(issue)" in script.text
    assert "async function insertImageAtSelection(position)" in script.text
    assert "function deleteSelectedImage()" in script.text
    assert "function openInsertTextDialog()" in script.text
    assert "function insertTextRow()" in script.text
    assert "function deleteSelectedBlock()" in script.text
    assert "function applyTextFontSize(target)" in script.text
    assert "function applyTextBlockUnderline(row)" in script.text
    assert 'const listItem = target.closest("li");' in script.text
    assert "function replaceListItemText(item, text)" in script.text
    assert 'selected.matches("li")' in script.text
    assert "function applyTableColumnWidth()" in script.text
    assert "function applyTableRowHeight()" in script.text
    assert "function refreshPointSizedTable(table)" in script.text
    assert "function applyTableCellBackground()" in script.text
    assert "function clearTableCellBackground()" in script.text
    assert "function copyCellPointSize(source, target)" in script.text
    assert "function insertTableRow(position)" in script.text
    assert "function deleteTableRow()" in script.text
    assert "function insertTableColumn(position)" in script.text
    assert "function deleteTableColumn()" in script.text
    assert "function insertTableAfterSelection()" in script.text

    flush = script.text.index("async function flushActiveDocument()")
    apply = script.text.index("async function applyIssue(id)")
    ignore = script.text.index("async function ignoreIssue(id)")
    assert script.text.index("await persistDocument(document, false)", flush, apply) < apply
    assert script.text.index("await flushActiveDocument()", apply, ignore) < script.text.index("/issues/", apply, ignore)
    assert script.text.index("await flushActiveDocument()", ignore) < script.text.index("/issues/", ignore)

    style = client.get("/static/style.css")
    assert "grid-template-columns:42px 84px minmax(0,1fr)" in style.text
    assert "padding-left:calc(var(--depth,0) * 22px)" in style.text


def test_frontend_script_only_references_existing_element_ids(client):
    index = client.get("/").text
    script = client.get("/static/app.js").text
    existing = {tag["id"] for tag in BeautifulSoup(index, "html.parser").select("[id]")}
    referenced = set(re.findall(r'\$\("([A-Za-z][A-Za-z0-9_-]*)"\)', script))

    assert referenced <= existing


def test_multiple_markdown_and_html_upload(client):
    response = client.post(
        "/api/documents",
        files=[
            ("files", ("first.md", b"# Overview", "text/markdown")),
            ("files", ("second.html", b"<h1>HTML</h1><p>body</p>", "text/html")),
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["filename"] for item in data["documents"]] == ["first.md", "second.html"]
    assert data["errors"] == []
    assert "# HTML" in data["documents"][1]["markdown"]


def test_markdown_upload_renders_compact_table_in_preview_and_html_download(client):
    markdown = "# 概要\n\n本文です。\n| 名称 | 型名 |\n|---|---|\n| 製品 | ABC |\n"
    created = client.post(
        "/api/documents",
        files=[("files", ("table.md", markdown.encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]

    preview = client.post(
        f'/api/documents/{created["session_id"]}/preview',
        json={"markdown": markdown},
    )
    downloaded = client.get(f'/api/documents/{created["session_id"]}/download/html')

    assert "<table>" in preview.text
    assert "<table>" in downloaded.text
    assert "<th>名称</th>" in downloaded.text


def test_upload_reports_partial_errors(client):
    response = client.post(
        "/api/documents",
        files=[
            ("files", ("valid.md", b"# Valid", "text/markdown")),
            ("files", ("invalid.txt", b"invalid", "text/plain")),
        ],
    )

    assert response.status_code == 200
    assert len(response.json()["documents"]) == 1
    assert response.json()["errors"][0]["filename"] == "invalid.txt"


def test_failed_conversion_removes_temporary_session(client, monkeypatch):
    def fail_conversion(*_args):
        raise RuntimeError("failed")

    monkeypatch.setattr(app_module, "document_to_markdown", fail_conversion)

    response = client.post(
        "/api/documents",
        files=[("files", ("manual.md", b"# Manual", "text/markdown"))],
    )

    assert response.status_code == 400
    assert not list(app_module.store.root.iterdir())


def test_edit_preview_and_download(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.html", "<h1>概要</h1>".encode(), "text/html"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    updated = client.put(
        f"/api/documents/{session_id}",
        json={"markdown": "# 更新後"},
    )
    preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": "# プレビュー"},
    )
    download = client.get(f"/api/documents/{session_id}/download/html")

    assert updated.status_code == 200
    assert updated.json()["markdown"] == "# 更新後"
    assert preview.status_code == 200
    assert "プレビュー" in preview.text
    assert download.status_code == 200
    assert "更新後" in download.text


def test_visual_edit_updates_content_without_accepting_style_or_script(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# １． 概要\n\n本文\n".encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    updated = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={
            "html": """
              <article><h1 style="color:red" onclick="alert(1)">１． 更新概要</h1>
              <p>更新本文</p><table><tr><th>名称</th><td>製品A</td></tr></table>
              <blockquote><p>注意内容</p></blockquote><script>alert(1)</script></article>
            """
        },
    )

    assert updated.status_code == 200
    markdown = updated.json()["markdown"]
    assert "# １． 更新概要" in markdown
    assert "更新本文" in markdown
    assert "<table>" in markdown
    assert "> 注意内容" in markdown
    assert "style=" not in markdown
    assert "onclick=" not in markdown
    assert "alert(1)" not in markdown
    downloaded = client.get(f"/api/documents/{session_id}/download/html")
    assert "更新概要" in downloaded.text
    assert "更新本文" in downloaded.text


def test_visual_edit_image_upload_uses_content_addressed_session_asset(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", b"# Manual", "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]
    image = b"\x89PNG\r\n\x1a\nmanual-tool-test"

    uploaded = client.post(
        f"/api/documents/{session_id}/assets/images",
        files={"file": ("replacement.png", image, "image/png")},
    )

    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["path"].startswith("images/replacements/replacement-")
    served = client.get(payload["preview_url"])
    assert served.status_code == 200
    assert served.content == image
    saved = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={"html": f'<p><img src="{payload["preview_url"]}" alt="差し替え画像"></p>'},
    )
    assert payload["path"] in saved.json()["markdown"]


def test_visual_edit_rejects_non_image_replacement(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", b"# Manual", "text/markdown"))],
    ).json()["documents"][0]

    response = client.post(
        f'/api/documents/{created["session_id"]}/assets/images',
        files={"file": ("not-image.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 415


def test_visual_edit_saves_inserted_table_and_allows_table_removal(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# 概要\n\n本文\n".encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]
    table = """
      <h1>概要</h1><p>本文</p><table><thead><tr><th>A</th><th>B</th></tr></thead>
      <tbody><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></tbody></table>
    """

    inserted = client.put(f"/api/documents/{session_id}/visual-edit", json={"html": table})
    inserted_preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": inserted.json()["markdown"]},
    )
    inserted_table = BeautifulSoup(inserted_preview.text, "html.parser").find("table")
    assert len(inserted_table.select("tr")) == 3
    assert len(inserted_table.select("th,td")) == 6

    removed = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={"html": "<h1>概要</h1><p>本文</p>"},
    )
    removed_preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": removed.json()["markdown"]},
    )
    assert BeautifulSoup(removed_preview.text, "html.parser").find("table") is None


def test_visual_edit_preserves_only_valid_gui_text_row_background(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# 概要\n\n本文\n".encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    updated = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={
            "html": """
              <h1>概要</h1>
              <div class="manual-text-row" data-manual-tool-background="#A1B2C3"
                   style="color:red" onclick="alert(1)"><p>追加した文字列</p></div>
              <div class="manual-text-row" data-manual-tool-background="red"
                   style="color:red"><p>背景指定なし</p></div>
            """
        },
    )

    assert updated.status_code == 200
    markdown = updated.json()["markdown"]
    assert 'class="manual-text-row"' in markdown
    assert 'style="background-color:#a1b2c3"' in markdown
    assert "color:red" not in markdown
    assert "onclick" not in markdown
    preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": markdown},
    )
    rows = BeautifulSoup(preview.text, "html.parser").select("div.manual-text-row")
    assert len(rows) == 2
    assert rows[0].get("style") == "background-color:#a1b2c3"
    assert rows[1].get("style") is None

    saved_again = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={"html": "".join(str(row) for row in rows)},
    )
    assert 'style="background-color:#a1b2c3"' in saved_again.json()["markdown"]

    removed = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={"html": "<h1>概要</h1><p>本文</p>"},
    )
    assert "manual-text-row" not in removed.json()["markdown"]


def test_visual_edit_preserves_safe_text_row_underline(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# 概要\n\n本文\n".encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    updated = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={
            "html": """
              <div class="manual-text-row" data-manual-tool-underline="thin"
                   data-manual-tool-underline-color="#AABBCC" style="border:20px solid red"><p>細線</p></div>
              <div class="manual-text-row" data-manual-tool-underline="thick"
                   data-manual-tool-underline-color="#112233"><p>太線</p></div>
              <div class="manual-text-row" data-manual-tool-underline="double"
                   data-manual-tool-underline-color="red" style="border-bottom:9pt double red"><p>無効</p></div>
              <p class="manual-underlined-block" data-manual-tool-underline="thick"
                 data-manual-tool-underline-color="#445566" style="border:20px solid red">既存本文</p>
              <p class="manual-underlined-block" data-manual-tool-underline="double"
                 data-manual-tool-underline-color="red" style="border-bottom:9pt double red">無効本文</p>
            """
        },
    )

    assert updated.status_code == 200
    markdown = updated.json()["markdown"]
    assert 'style="border-bottom:1pt solid #aabbcc"' in markdown
    assert 'style="border-bottom:3pt solid #112233"' in markdown
    assert '<p class="manual-underlined-block" style="border-bottom:3pt solid #445566">既存本文</p>' in markdown
    assert '<p class="manual-underlined-block"' in markdown
    assert "20px" not in markdown
    assert "9pt" not in markdown
    assert "double" not in markdown
    preview = client.post(f"/api/documents/{session_id}/preview", json={"markdown": markdown})
    rows = BeautifulSoup(preview.text, "html.parser").select("div.manual-text-row")
    paragraphs = BeautifulSoup(preview.text, "html.parser").select("p.manual-underlined-block")
    assert rows[0].get("style") == "border-bottom:1pt solid #aabbcc"
    assert rows[1].get("style") == "border-bottom:3pt solid #112233"
    assert rows[2].get("style") is None
    assert paragraphs[0].get("style") == "border-bottom:3pt solid #445566"
    assert "無効本文" not in [paragraph.get_text() for paragraph in paragraphs]


def test_visual_edit_preserves_safe_font_size(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# 概要\n\n本文\n".encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    updated = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={
            "html": """
              <h1>概要</h1>
              <p><span class="manual-font-size manual-bold" data-manual-tool-font-size="14.5"
                 style="color:red" onclick="alert(1)">サイズ変更</span></p>
              <p><span class="manual-bold" style="font-weight:100;color:red">太字のみ</span></p>
              <p><span class="manual-font-size" data-manual-tool-font-size="100"
                 style="font-size:100pt;color:red">範囲外</span></p>
            """
        },
    )

    assert updated.status_code == 200
    markdown = updated.json()["markdown"]
    assert 'class="manual-font-size manual-bold" style="font-size:14.5pt;font-weight:700"' in markdown
    assert 'class="manual-bold" style="font-weight:700"' in markdown
    assert "font-size:100pt" not in markdown
    assert "color:red" not in markdown
    assert "onclick" not in markdown
    preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": markdown},
    )
    soup = BeautifulSoup(preview.text, "html.parser")
    assert soup.select_one("span.manual-font-size").get("style") == "font-size:14.5pt;font-weight:700"
    assert soup.select_one("span.manual-bold:not(.manual-font-size)").get("style") == "font-weight:700"


def test_visual_edit_preserves_safe_table_cell_points_and_background(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# 概要\n\n本文\n".encode("utf-8"), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    updated = client.put(
        f"/api/documents/{session_id}/visual-edit",
        json={
            "html": """
              <table class="manual-table-points"><tr>
                <th data-manual-tool-cell-width="90" data-manual-tool-cell-height="24.5"
                    data-manual-tool-cell-background="transparent"
                    style="color:red" onclick="alert(1)">A</th>
                <td data-manual-tool-cell-width="90" data-manual-tool-cell-height="24.5"
                    data-manual-tool-cell-background="#AABBCC">B</td>
                <td data-manual-tool-cell-width="900" data-manual-tool-cell-height="1"
                    data-manual-tool-cell-background="red" style="color:red">C</td>
              </tr></table>
            """
        },
    )

    assert updated.status_code == 200
    markdown = updated.json()["markdown"]
    assert 'class="manual-table-points"' in markdown
    assert 'style="background-color:transparent;width:90pt;min-width:90pt;height:24.5pt"' in markdown
    assert 'style="background-color:#aabbcc;width:90pt;min-width:90pt;height:24.5pt"' in markdown
    assert "width:900pt" not in markdown
    assert "height:1pt" not in markdown
    assert "color:red" not in markdown
    assert "onclick" not in markdown
    preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": markdown},
    )
    cells = BeautifulSoup(preview.text, "html.parser").select("th,td")
    assert cells[0].get("style") == "background-color:transparent;width:90pt;min-width:90pt;height:24.5pt"
    assert cells[1].get("style") == "background-color:#aabbcc;width:90pt;min-width:90pt;height:24.5pt"
    assert cells[2].get("style") is None


def test_ignored_issue_is_marked_in_downloaded_report(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "# 概要\n\n適切に処理する。".encode(), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]
    ignored_id = created["issues"][0]["id"]

    ignored = client.post(f"/api/documents/{session_id}/issues/{ignored_id}/ignore")
    report = client.get(f"/api/documents/{session_id}/download/report")

    assert ignored.status_code == 200
    assert ignored_id not in {issue["id"] for issue in ignored.json()["issues"]}
    report_items = json.loads(report.text)
    assert next(issue for issue in report_items if issue["id"] == ignored_id)["ignored"] is True
    assert all("ignored" in issue for issue in report_items)


def test_preview_and_download_promote_the_highest_heading_to_h1(client):
    created = client.post(
        "/api/documents",
        files=[("files", ("manual.md", "## 章\n\n### 節\n".encode(), "text/markdown"))],
    ).json()["documents"][0]
    session_id = created["session_id"]

    assert created["markdown"] == "# 章\n\n## 節\n"

    edited_markdown = "### ２. 更新章\n\n#### ２．２． 更新節\n"
    client.put(f"/api/documents/{session_id}", json={"markdown": edited_markdown})
    preview = client.post(
        f"/api/documents/{session_id}/preview",
        json={"markdown": edited_markdown},
    )
    markdown_download = client.get(f"/api/documents/{session_id}/download/markdown")

    preview_page = BeautifulSoup(preview.text, "html.parser")
    assert preview_page.select_one("h1").get_text(strip=True) == "１． 更新章"
    assert preview_page.select_one("h2").get_text(strip=True) == "１．１． 更新節"
    assert markdown_download.text == "# １． 更新章\n\n## １．１． 更新節\n"
