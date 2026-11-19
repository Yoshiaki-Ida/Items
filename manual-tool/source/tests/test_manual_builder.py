from __future__ import annotations

import json

from bs4 import BeautifulSoup
import pytest

from manual_tool.assembly.builder import ManualValidationError, build_manual
from manual_tool.assembly.schema import ManualDefinition, ManualNode, save_manual
from manual_tool.assembly.validator import validate_manual
from manual_tool.renderer import LEGACY_DOCUMENT_STYLE, render_document


def write_part(source, name, title, body=""):
    path = source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<!doctype html><html><body><h1>{title}</h1>{body}</body></html>", encoding="utf-8")
    return path


def project(tmp_path, definition):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    yaml_path = tmp_path / "manual.yaml"
    save_manual(yaml_path, definition)
    return source, yaml_path


def heading_texts(output):
    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    return [
        heading.get_text(" ", strip=True)
        for heading in soup.select(".front-matter > h1, .manual-content h2, .manual-content h3, .manual-content h4")
    ]


def test_build_single_chapter_and_toc(tmp_path):
    definition = ManualDefinition("製品マニュアル", chapters=[ManualNode("overview", "概要", "overview.html")])
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "overview.html", "元タイトル", "<p>本文</p>")

    result = build_manual(yaml_path)
    html = result.output_path.read_text(encoding="utf-8")

    assert result.output_path == tmp_path / "output" / "manual.html"
    assert '<h2 id="overview">1. 概要</h2>' in html
    assert '<a href="#overview"><span class="toc-label">1. 概要</span>' in html
    assert "本文" in html


def test_build_multiple_chapters_uses_yaml_order(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[ManualNode("stop", "停止", "stop.html"), ManualNode("start", "起動", "start.html")],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "start.html", "起動")
    write_part(source, "stop.html", "停止")

    output = build_manual(yaml_path).output_path

    assert heading_texts(output)[:3] == ["Manual", "1. 停止", "2. 起動"]


def test_build_removes_document_css_and_deduplicates_custom_css(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[ManualNode("a", "A", "a.html"), ManualNode("b", "B", "b.html")],
    )
    source, yaml_path = project(tmp_path, definition)
    custom_style = "<style>.custom-rule{color:#123456}</style>"
    for name in ("a", "b"):
        html = render_document(f"# {name.upper()}\n\n本文", name)
        html = html.replace("</head>", f"{custom_style}</head>")
        (source / f"{name}.html").write_text(html, encoding="utf-8")
    legacy_html = (
        "<!doctype html><html><head>"
        f"<style>{LEGACY_DOCUMENT_STYLE}</style>{custom_style}</head>"
        "<body><h1>C</h1><p>本文</p></body></html>"
    )
    (source / "c.html").write_text(legacy_html, encoding="utf-8")
    definition.chapters.append(ManualNode("c", "C", "c.html"))
    save_manual(yaml_path, definition)

    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert "article{max-width:980px;margin:auto;padding:32px 48px}" not in html
    assert html.count(".custom-rule{color:#123456}") == 1


def test_build_keeps_table_note_and_code_presentation_in_combined_css(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("part", "Part", "part.html")])
    source, yaml_path = project(tmp_path, definition)
    write_part(
        source,
        "part.html",
        "Part",
        "<table><tr><th>見出し</th></tr><tr><td>内容</td></tr></table>"
        "<blockquote><p><strong>設計メモ</strong><br>補足</p></blockquote>"
        "<pre>code</pre>",
    )

    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert "th{background:#eaf2f8;font-weight:700}" in html
    assert "background:#eef6ff;color:#52667a" in html
    assert "background:#17202a;color:#f4f6f7" in html


def test_build_allows_html_node_children(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode(
                "overview",
                "概要",
                "overview.html",
                children=[ManualNode("setup", "セットアップ", "setup.html")],
            )
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "overview.html", "概要", "<p>概要本文</p>")
    write_part(source, "setup.html", "セットアップ", "<p>設定本文</p>")

    output = build_manual(yaml_path).output_path

    assert heading_texts(output)[:3] == ["Manual", "1. 概要", "1.1. セットアップ"]


def test_html_direct_headings_and_child_nodes_share_one_number_sequence(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode(
                "system",
                "システム構成",
                "system.html",
                children=[ManualNode("equipment", "構成機器", "equipment.html")],
            )
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "system.html", "システム構成", "<h2>システム構成</h2><p>本文</p>")
    write_part(source, "equipment.html", "構成機器", "<p>本文</p>")

    output = build_manual(yaml_path).output_path
    html = output.read_text(encoding="utf-8")

    assert heading_texts(output)[:4] == ["Manual", "1. システム構成", "1.1. システム構成", "1.2. 構成機器"]
    assert '<span class="toc-label">1.2. 構成機器</span>' in html


def test_build_includes_unnumbered_html_in_toc_without_chapter_number(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode("revision", "改訂履歴", "revision.html", numbered=False),
            ManualNode("overview", "概要", "overview.html"),
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "revision.html", "改訂履歴", "<p>履歴本文</p>")
    write_part(source, "overview.html", "概要", "<p>概要本文</p>")

    output = build_manual(yaml_path).output_path
    html = output.read_text(encoding="utf-8")

    assert "改訂履歴" in html
    assert "履歴本文" in html
    assert "1. 改訂履歴" not in html
    assert '<a href="#revision"><span class="toc-label">改訂履歴</span>' in html
    assert '<h2 id="revision">改訂履歴</h2>' in html
    assert '<h2 id="overview">1. 概要</h2>' in html


def test_build_adds_a4_print_layout_and_toc_page_numbers(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("overview", "概要", "overview.html")])
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "overview.html", "概要", "<p>本文</p>")

    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert "--paper-width:210mm" in html
    assert "--paper-height:297mm" in html
    assert "@page{size:A4" in html
    assert 'class="a4-paper front-matter"' in html
    assert 'class="a4-paper manual-content"' in html
    assert 'id="paged-content"' in html
    assert '<span class="toc-leader"' in html
    assert '<span class="toc-page" data-target="overview"' in html
    assert "paginateManual" in html
    assert "let pageNumber = 0" in html


def test_build_starts_each_top_level_chapter_on_a_new_page(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode("overview", "概要", "overview.html"),
            ManualNode("setup", "設定", "setup.html"),
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "overview.html", "概要", "<p>概要本文</p>")
    write_part(source, "setup.html", "設定", "<p>設定本文</p>")

    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert html.count('class="manual-section level-1"') == 2
    assert "blocks.push({chapterBreak: true})" in html
    assert "if (pageBody.children.length) addPage()" in html
    assert ".manual-content>.manual-section.level-1:not(:first-child){break-before:page}" in html


def test_paginator_unwraps_part_articles_and_splits_long_tables_by_row(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("terms", "用語", "terms.html")])
    source, yaml_path = project(tmp_path, definition)
    write_part(
        source,
        "terms.html",
        "用語",
        "<article><p>説明</p><table><thead><tr><th>用語</th></tr></thead>"
        "<tbody><tr><td>A</td></tr><tr><td>B</td></tr></tbody></table></article>",
    )

    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert "node.matches('section.manual-section, article')" in html
    assert "const placeTableByRows = table =>" in html
    assert "child.tagName === 'THEAD'" in html
    assert "block.tagName === 'TABLE' && placeTableByRows(block)" in html


def test_three_level_structure_and_internal_heading_numbering(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode(
                "operation",
                "基本操作",
                children=[
                    ManualNode(
                        "startup-group",
                        "起動系",
                        children=[ManualNode("startup", "起動", "startup.html")],
                    )
                ],
            )
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "startup.html", "起動", "<h2>実行条件</h2><p>条件</p>")

    output = build_manual(yaml_path).output_path
    html = output.read_text(encoding="utf-8")

    assert "1. 基本操作" in html
    assert "1.1. 起動系" in html
    assert "1.1.1. 起動" in html
    assert "1.1.1.1. 実行条件" in html
    assert "<h5" in html


def test_reorder_add_and_delete_recalculates_all_numbers(tmp_path):
    chapters = [
        ManualNode("a", "A", "a.html"),
        ManualNode("b", "B", "b.html"),
        ManualNode("c", "C", "c.html"),
    ]
    definition = ManualDefinition("Manual", chapters=chapters)
    source, yaml_path = project(tmp_path, definition)
    for name in ("a", "b", "c", "d"):
        write_part(source, f"{name}.html", name.upper())

    definition.chapters = [chapters[2], ManualNode("d", "D", "d.html"), chapters[0]]
    save_manual(yaml_path, definition)
    output = build_manual(yaml_path).output_path

    assert heading_texts(output)[:4] == ["Manual", "1. C", "2. D", "3. A"]


def test_source_headings_are_shifted_to_logical_output_levels(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[ManualNode("group", "Group", children=[ManualNode("home", "原点復帰", "home.html")])],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "home.html", "原点復帰", "<h2>実行条件</h2><h3>詳細</h3><h2>操作方法</h2>")

    soup = BeautifulSoup(build_manual(yaml_path).output_path.read_text(encoding="utf-8"), "html.parser")

    assert soup.find("h3", string="1.1. 原点復帰") is not None
    assert soup.find("h4", string="1.1.1. 実行条件") is not None
    assert soup.find("h5", string="1.1.1.1. 詳細") is not None
    assert soup.find("h4", string="1.1.2. 操作方法") is not None


@pytest.mark.parametrize(
    ("node", "expected_code"),
    [
        (ManualNode("missing", "Missing", "missing.html"), "file-missing"),
        (ManualNode("empty", "", "part.html"), "node-title"),
    ],
)
def test_validation_rejects_missing_file_and_empty_title(tmp_path, node, expected_code):
    definition = ManualDefinition("Manual", chapters=[node])
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "part.html", "Part")

    issues = validate_manual(definition, yaml_path)

    assert expected_code in {issue.code for issue in issues}


def test_validation_rejects_empty_manual_title_and_structure(tmp_path):
    definition = ManualDefinition("", chapters=[])
    _, yaml_path = project(tmp_path, definition)

    codes = {issue.code for issue in validate_manual(definition, yaml_path)}

    assert {"manual-title", "chapters-empty"} <= codes


def test_validation_rejects_duplicate_file_and_id(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[ManualNode("same", "A", "part.html"), ManualNode("same", "B", "part.html")],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "part.html", "Part")

    codes = {issue.code for issue in validate_manual(definition, yaml_path)}

    assert {"duplicate-id", "duplicate-file"} <= codes


def test_validation_rejects_output_that_overwrites_source_html(tmp_path):
    definition = ManualDefinition(
        "Manual",
        source_dir="source",
        output="source/part.html",
        chapters=[ManualNode("part", "Part", "part.html")],
    )
    source, yaml_path = project(tmp_path, definition)
    source_path = write_part(source, "part.html", "Original", "<p>原本</p>")
    original = source_path.read_bytes()

    issues = validate_manual(definition, yaml_path)

    assert "output-conflicts-source" in {issue.code for issue in issues}
    with pytest.raises(ManualValidationError):
        build_manual(yaml_path)
    assert source_path.read_bytes() == original


def test_validation_rejects_fourth_structure_level(tmp_path):
    leaf = ManualNode("leaf", "Leaf", "leaf.html")
    level_three = ManualNode("level-three", "Level 3", children=[leaf])
    level_two = ManualNode("level-two", "Level 2", "parent.html", children=[level_three])
    definition = ManualDefinition("Manual", chapters=[ManualNode("level-one", "Level 1", children=[level_two])])
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "leaf.html", "Leaf")
    write_part(source, "parent.html", "Parent")

    codes = {issue.code for issue in validate_manual(definition, yaml_path)}

    assert "hierarchy-depth" in codes
    assert "file-with-children" not in codes


def test_validation_rejects_invalid_heading_structure(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("bad", "Bad", "bad.html")])
    source, yaml_path = project(tmp_path, definition)
    (source / "bad.html").write_text("<html><body><h2>見出し</h2><h4>飛び</h4></body></html>", encoding="utf-8")

    codes = {issue.code for issue in validate_manual(definition, yaml_path)}

    assert {"heading-root", "heading-h1-count", "heading-jump"} <= codes
    with pytest.raises(ManualValidationError):
        build_manual(yaml_path)


def test_validation_rejects_missing_asset(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("image", "Image", "image.html")])
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "image.html", "Image", '<img src="missing.png">')

    issues = validate_manual(definition, yaml_path)

    assert "asset-missing" in {issue.code for issue in issues}


def test_build_copies_and_rewrites_local_assets(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("image", "Image", "image.html")])
    source, yaml_path = project(tmp_path, definition)
    (source / "images").mkdir()
    (source / "images" / "figure.png").write_bytes(b"image")
    write_part(source, "image.html", "Image", '<img src="images/figure.png">')

    output = build_manual(yaml_path).output_path
    html = output.read_text(encoding="utf-8")

    assert 'src="source/images/figure.png"' in html
    assert (tmp_path / "output" / "source" / "images" / "figure.png").read_bytes() == b"image"


def test_rebuild_removes_only_assets_no_longer_generated(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("image", "Image", "image.html")])
    source, yaml_path = project(tmp_path, definition)
    images = source / "images"
    images.mkdir()
    (images / "old.png").write_bytes(b"old")
    write_part(source, "image.html", "Image", '<img src="images/old.png">')

    output = build_manual(yaml_path).output_path.parent
    unrelated = output / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    old_output = output / "source" / "images" / "old.png"
    assert old_output.exists()

    (images / "old.png").unlink()
    (images / "new.png").write_bytes(b"new")
    write_part(source, "image.html", "Image", '<img src="images/new.png">')
    build_manual(yaml_path)

    assert not old_output.exists()
    assert (output / "source" / "images" / "new.png").read_bytes() == b"new"
    assert unrelated.read_text(encoding="utf-8") == "keep"
    report = json.loads((output / "build-report.json").read_text(encoding="utf-8"))
    assert report["generated_files"] == ["source/images/new.png"]


def test_build_is_deterministic_for_same_inputs(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("overview", "概要", "overview.html")])
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "overview.html", "概要", "<h2>詳細</h2>")

    first = build_manual(yaml_path).output_path.read_bytes()
    second = build_manual(yaml_path).output_path.read_bytes()

    assert second == first


def test_build_replaces_file_local_heading_numbers_with_structure_numbers(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode("first", "1. はじめに", "first.html"),
            ManualNode("numbered", "２． 概要", "numbered.html"),
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "first.html", "1. はじめに")
    write_part(source, "numbered.html", "２． 概要", "<h2>２．２． 詳細</h2>")

    issues = validate_manual(definition, yaml_path)
    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert not issues
    assert '<h2 id="numbered">2. 概要</h2>' in html
    assert ">2.1. 詳細</h3>" in html
    assert "2. ２． 概要" not in html


def test_validation_reports_non_utf8_html_as_parse_failure(tmp_path):
    definition = ManualDefinition("Manual", chapters=[ManualNode("broken", "Broken", "broken.html")])
    source, yaml_path = project(tmp_path, definition)
    (source / "broken.html").write_bytes(b"\x82\xa0")

    codes = {issue.code for issue in validate_manual(definition, yaml_path)}

    assert "html-parse" in codes


def test_stable_data_reference_resolves_without_using_number_as_key(tmp_path):
    definition = ManualDefinition(
        "Manual",
        chapters=[
            ManualNode("overview", "概要", "overview.html"),
            ManualNode("home-operation", "原点復帰", "home.html"),
        ],
    )
    source, yaml_path = project(tmp_path, definition)
    write_part(source, "overview.html", "概要", '<p><a data-ref="home-operation"></a></p>')
    write_part(source, "home.html", "原点復帰")

    html = build_manual(yaml_path).output_path.read_text(encoding="utf-8")

    assert '<a data-ref="home-operation" href="#home-operation">2. 原点復帰</a>' in html
